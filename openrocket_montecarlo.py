"""
OpenRocket Monte Carlo Automation via JPype
===========================================
Executa N simulações variando parâmetros do foguete,
coleta métricas e ranqueia o design mais estável.

Requisitos:
  pip install jpype1 numpy pandas rich
  Java 11+ instalado
  OpenRocket JAR em OPENROCKET_JAR
  Um arquivo .ork base em ROCKET_ORK

Uso:
  python openrocket_montecarlo.py
  python openrocket_montecarlo.py --runs 5000 --output resultados.csv
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import random
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────
# CONFIGURAÇÃO — edite aqui
# ─────────────────────────────────────────────
OPENROCKET_JAR = Path("openrocket-15.03.jar")   # caminho para o JAR
ROCKET_ORK     = Path("base_rocket.ork")         # arquivo base do foguete

# Parâmetros Monte Carlo (fator multiplicador em relação ao valor base)
PARAM_RANGES = {
    # componente : (min_factor, max_factor)
    "nose_length":       (0.80, 1.20),
    "body_tube_length":  (0.85, 1.15),
    "fin_root_chord":    (0.75, 1.25),
    "fin_tip_chord":     (0.75, 1.25),
    "fin_span":          (0.80, 1.20),
    "fin_sweep_angle":   (0.70, 1.30),   # degrees
}

# Condições de lançamento variáveis
LAUNCH_RANGES = {
    "launch_angle_deg":  (85.0, 90.0),   # 90 = vertical
    "wind_speed_mps":    (0.0,  5.0),
    "launch_altitude_m": (0.0, 50.0),
}

# Critérios de estabilidade
STABILITY_MIN  = 1.0   # margem mínima aceitável (calibers)
STABILITY_IDEAL_LOW  = 1.5
STABILITY_IDEAL_HIGH = 2.5

# ─────────────────────────────────────────────────────────────────────────────
# DATACLASS de resultado
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SimResult:
    run_id:           int
    stability_margin: float   # em calibers (CP - CG) / diâmetro
    max_altitude_m:   float
    max_velocity_mps: float
    flight_time_s:    float
    stability_score:  float   # score composto (0-100)
    params:           dict    = field(default_factory=dict)
    launch:           dict    = field(default_factory=dict)
    error:            Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO JVM + OPENROCKET
# ─────────────────────────────────────────────────────────────────────────────
def start_jvm(jar: Path):
    import jpype
    if jpype.isJVMStarted():
        return
    if not jar.exists():
        raise FileNotFoundError(f"JAR não encontrado: {jar}")
    
    jpype.startJVM(
        jpype.getDefaultJVMPath(),
        f"-Djava.class.path={jar.resolve()}",
        "-Xmx1g",
        "-Djava.awt.headless=true",
        "--add-opens=java.base/java.lang=ALL-UNNAMED",   # ← necessário no Java 17+
        "--add-opens=java.base/java.util=ALL-UNNAMED",
        convertStrings=False,
    )
    
    # Confirma que o JAR foi carregado
    import jpype.imports
    print(f"[JVM] iniciada — {jpype.getDefaultJVMPath()}")

def init_openrocket():
    """
    OpenRocket usa Google Guice para injeção de dependência.
    Precisa inicializar o Application antes de qualquer operação.
    """
    import jpype.imports
    from net.sf.openrocket.startup import Application
    from net.sf.openrocket.plugin import PluginModule
    from com.google.inject import Guice

    modules = [PluginModule()]
    injector = Guice.createInjector(modules)
    Application.setInjector(injector)
    print("[OpenRocket] Application inicializado")


def load_rocket(ork_path: Path):
    """Carrega um .ork e retorna (OpenRocketDocument, Rocket)."""
    from net.sf.openrocket.file import GeneralRocketLoader
    from net.sf.openrocket.aerodynamics import WarningSet
    from java.io import File

    if not ork_path.exists():
        raise FileNotFoundError(f".ork não encontrado: {ork_path}")

    loader = GeneralRocketLoader(File(str(ork_path)))
    warnings = WarningSet()
    doc = loader.load(warnings)
    if warnings.size() > 0:
        print(f"[load] {warnings.size()} aviso(s) ao carregar .ork")
    return doc, doc.getRocket()


# ─────────────────────────────────────────────────────────────────────────────
# MANIPULAÇÃO DE COMPONENTES
# ─────────────────────────────────────────────────────────────────────────────
def find_component(rocket, java_type_name: str, index: int = 0):
    """
    Percorre a árvore de componentes e retorna o N-ésimo componente
    do tipo informado (ex: 'NoseCone', 'BodyTube', 'TrapezoidFinSet').
    """
    from net.sf.openrocket.rocketcomponent import (
        NoseCone, BodyTube, TrapezoidFinSet, EllipticalFinSet,
        FreeformFinSet, RocketComponent
    )
    type_map = {
        "NoseCone":          NoseCone,
        "BodyTube":          BodyTube,
        "TrapezoidFinSet":   TrapezoidFinSet,
        "EllipticalFinSet":  EllipticalFinSet,
        "FreeformFinSet":    FreeformFinSet,
    }
    target_class = type_map.get(java_type_name)
    if target_class is None:
        raise ValueError(f"Tipo desconhecido: {java_type_name}")

    results = []
    _walk_components(rocket, target_class, results)
    if index >= len(results):
        raise IndexError(f"Componente [{java_type_name}] índice {index} não encontrado")
    return results[index]


def _walk_components(component, target_class, found: list):
    if isinstance(component, target_class):
        found.append(component)
    for i in range(component.getChildCount()):
        _walk_components(component.getChild(i), target_class, found)


def apply_params(rocket, base_values: dict, factors: dict):
    """
    Aplica os fatores Monte Carlo sobre os valores base.
    base_values = {"nose_length": 0.3, "fin_span": 0.08, ...} em metros/graus
    """
    from net.sf.openrocket.rocketcomponent import TrapezoidFinSet

    # Nose cone
    try:
        nose = find_component(rocket, "NoseCone")
        nose.setLength(base_values["nose_length"] * factors["nose_length"])
    except Exception:
        pass

    # Body tube (primeiro)
    try:
        body = find_component(rocket, "BodyTube")
        body.setLength(base_values["body_tube_length"] * factors["body_tube_length"])
    except Exception:
        pass

    # Fin set (trapezoidal)
    try:
        fins = find_component(rocket, "TrapezoidFinSet")
        fins.setRootChord(base_values["fin_root_chord"] * factors["fin_root_chord"])
        fins.setTipChord(base_values["fin_tip_chord"]  * factors["fin_tip_chord"])
        fins.setHeight(base_values["fin_span"]         * factors["fin_span"])
        # sweep angle em radianos
        import math
        sweep_deg = base_values["fin_sweep_angle_deg"] * factors["fin_sweep_angle"]
        fins.setSweepAngle(math.radians(sweep_deg))
    except Exception:
        pass


def read_base_values(rocket) -> dict:
    """Lê os valores originais dos componentes para usar como referência."""
    import math
    vals = {}
    try:
        nose = find_component(rocket, "NoseCone")
        vals["nose_length"] = float(nose.getLength())
    except Exception:
        vals["nose_length"] = 0.3

    try:
        body = find_component(rocket, "BodyTube")
        vals["body_tube_length"] = float(body.getLength())
        vals["body_diameter"]    = float(body.getOuterRadius()) * 2
    except Exception:
        vals["body_tube_length"] = 1.0
        vals["body_diameter"]    = 0.064

    try:
        fins = find_component(rocket, "TrapezoidFinSet")
        vals["fin_root_chord"]     = float(fins.getRootChord())
        vals["fin_tip_chord"]      = float(fins.getTipChord())
        vals["fin_span"]           = float(fins.getHeight())
        vals["fin_sweep_angle_deg"] = math.degrees(float(fins.getSweepAngle()))
    except Exception:
        vals.setdefault("fin_root_chord",      0.08)
        vals.setdefault("fin_tip_chord",       0.04)
        vals.setdefault("fin_span",            0.06)
        vals.setdefault("fin_sweep_angle_deg", 30.0)

    return vals


# ─────────────────────────────────────────────────────────────────────────────
# SIMULAÇÃO
# ─────────────────────────────────────────────────────────────────────────────
def run_simulation(doc, rocket, launch_params: dict) -> dict:
    """
    Executa uma simulação e retorna as métricas extraídas.
    """
    from net.sf.openrocket.simulation import SimulationOptions
    from net.sf.openrocket.simulation.exception import SimulationException
    from net.sf.openrocket.masscalc import BasicMassCalculator
    from net.sf.openrocket.aerodynamics import AerodynamicForces, BarrowmanCalculator, FlightConditions, WarningSet
    from net.sf.openrocket.document import Simulation
    import math

    # Pega a primeira simulação do documento (ou cria uma)
    if doc.getSimulationCount() == 0:
        sim = Simulation(doc, rocket)
        doc.addSimulation(sim)
    else:
        sim = doc.getSimulation(0)

    opts = sim.getOptions()
    opts.setLaunchRodAngle(math.radians(90.0 - launch_params["launch_angle_deg"]))
    opts.setWindSpeedAverage(launch_params["wind_speed_mps"])
    opts.setLaunchAltitude(launch_params["launch_altitude_m"])

    # Executa
    try:
        sim.simulate()
    except Exception as e:
        return {"error": str(e)}

    # Extrai branch de dados
    branch = sim.getSimulatedData().getBranch(0)

    # Funções auxiliares para pegar o máximo de uma variável de voo
    def get_max(flight_data_type):
        try:
            data_type = _get_flight_data_type(flight_data_type)
            values = branch.get(data_type)
            if values is None:
                return 0.0
            return float(max(v.value for v in values))
        except Exception:
            return 0.0

    def get_last(flight_data_type):
        try:
            data_type = _get_flight_data_type(flight_data_type)
            values = branch.get(data_type)
            if values is None:
                return 0.0
            return float(list(values)[-1].value)
        except Exception:
            return 0.0

    # Estabilidade: calculada via Barrowman no momento do lançamento
    stability_margin = _calc_stability(rocket)

    return {
        "stability_margin": stability_margin,
        "max_altitude_m":   get_max("ALTITUDE"),
        "max_velocity_mps": get_max("VELOCITY_TOTAL"),
        "flight_time_s":    get_last("TIME"),
        "error": None,
    }


def _get_flight_data_type(name: str):
    from net.sf.openrocket.simulation import FlightDataType
    mapping = {
        "ALTITUDE":       FlightDataType.TYPE_ALTITUDE,
        "VELOCITY_TOTAL": FlightDataType.TYPE_VELOCITY_TOTAL,
        "TIME":           FlightDataType.TYPE_TIME,
        "STABILITY":      FlightDataType.TYPE_STABILITY,
    }
    return mapping[name]


def _calc_stability(rocket) -> float:
    """
    Calcula margem de estabilidade estática (calibers) via Barrowman.
    stability_margin = (CP_pos - CG_pos) / diâmetro_referência
    """
    from net.sf.openrocket.aerodynamics import (
        BarrowmanCalculator, FlightConditions, WarningSet, AerodynamicForces
    )
    from net.sf.openrocket.masscalc import BasicMassCalculator, MassCalcType

    try:
        conditions = FlightConditions(rocket)
        conditions.setMach(0.3)          # velocidade subsônica representativa
        conditions.setAOA(0.0)           # ângulo de ataque = 0
        conditions.setRollRate(0.0)
        conditions.setAtmosphericConditions(
            conditions.getAtmosphericConditions()
        )

        warnings  = WarningSet()
        calc      = BarrowmanCalculator()
        forces    = AerodynamicForces()
        calc.getAerodynamicForces(rocket, conditions, forces, warnings)

        cp_pos = float(forces.getCP().x)

        mass_calc = BasicMassCalculator()
        cg        = mass_calc.getCG(rocket, MassCalcType.LAUNCH_MASS)
        cg_pos    = float(cg.x)

        ref_diam  = float(conditions.getRefLength())   # diâmetro de referência
        if ref_diam <= 0:
            return 0.0

        return (cp_pos - cg_pos) / ref_diam
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# SCORE DE ESTABILIDADE (0-100)
# ─────────────────────────────────────────────────────────────────────────────
def compute_score(stability: float, altitude: float, velocity: float) -> float:
    """
    Score composto:
      - Estabilidade (60 pts): penaliza < 1.0 e > 3.0, máximo na faixa 1.5–2.5
      - Altitude     (30 pts): normalizada entre os resultados (calculada depois)
      - Velocidade   (10 pts): bônus para velocidades razoáveis
    Esta função retorna a componente de estabilidade + velocidade (altitude é relativa).
    """
    # Estabilidade
    if stability < STABILITY_MIN:
        stab_score = 0.0   # foguete instável — descartado
    elif STABILITY_IDEAL_LOW <= stability <= STABILITY_IDEAL_HIGH:
        stab_score = 60.0
    elif stability < STABILITY_IDEAL_LOW:
        # linear de 0 → 60 entre 1.0 e 1.5
        stab_score = 60.0 * (stability - STABILITY_MIN) / (STABILITY_IDEAL_LOW - STABILITY_MIN)
    else:
        # penalidade acima de 2.5 (superdominância de arrasto)
        stab_score = max(0.0, 60.0 - (stability - STABILITY_IDEAL_HIGH) * 15)

    # Velocidade (10 pts) — penaliza extremos
    vel_score = min(10.0, velocity / 50.0)  # 500 m/s → 10 pts

    return stab_score + vel_score


# ─────────────────────────────────────────────────────────────────────────────
# LOOP MONTE CARLO
# ─────────────────────────────────────────────────────────────────────────────
def monte_carlo(n_runs: int, doc, rocket, base_values: dict,
                seed: int = 42) -> list[SimResult]:
    rng = random.Random(seed)
    results: list[SimResult] = []

    print(f"\n{'─'*60}")
    print(f"  Iniciando Monte Carlo: {n_runs} simulações")
    print(f"{'─'*60}\n")

    t0 = time.perf_counter()

    for i in range(n_runs):
        # Sorteio de fatores
        factors = {
            k: rng.uniform(*v) for k, v in PARAM_RANGES.items()
        }
        launch = {
            k: rng.uniform(*v) for k, v in LAUNCH_RANGES.items()
        }

        # Aplica parâmetros no foguete (modifica in-place)
        apply_params(rocket, base_values, factors)

        # Simula
        raw = run_simulation(doc, rocket, launch)

        if raw.get("error"):
            results.append(SimResult(
                run_id=i, stability_margin=0, max_altitude_m=0,
                max_velocity_mps=0, flight_time_s=0, stability_score=0,
                params=factors, launch=launch, error=raw["error"]
            ))
        else:
            score = compute_score(
                raw["stability_margin"],
                raw["max_altitude_m"],
                raw["max_velocity_mps"],
            )
            results.append(SimResult(
                run_id=i,
                stability_margin=raw["stability_margin"],
                max_altitude_m=raw["max_altitude_m"],
                max_velocity_mps=raw["max_velocity_mps"],
                flight_time_s=raw["flight_time_s"],
                stability_score=score,
                params=factors,
                launch=launch,
                error=None,
            ))

        # Progresso a cada 10%
        if (i + 1) % max(1, n_runs // 10) == 0:
            pct = (i + 1) / n_runs * 100
            elapsed = time.perf_counter() - t0
            rate = (i + 1) / elapsed
            eta  = (n_runs - i - 1) / rate
            print(f"  {pct:5.1f}% | run {i+1:>6}/{n_runs} | "
                  f"{rate:.1f} sim/s | ETA {eta:.0f}s")

    # Normaliza score de altitude (30 pts)
    valid = [r for r in results if r.error is None]
    if valid:
        max_alt = max(r.max_altitude_m for r in valid) or 1.0
        for r in valid:
            r.stability_score += 30.0 * (r.max_altitude_m / max_alt)

    elapsed = time.perf_counter() - t0
    success = sum(1 for r in results if r.error is None)
    print(f"\n  Concluído: {success}/{n_runs} simulações válidas em {elapsed:.1f}s")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# ANÁLISE E RELATÓRIO
# ─────────────────────────────────────────────────────────────────────────────
def analyze(results: list[SimResult], top_n: int = 10) -> pd.DataFrame:
    rows = []
    for r in results:
        row = {
            "run_id":           r.run_id,
            "stability_margin": round(r.stability_margin, 3),
            "max_altitude_m":   round(r.max_altitude_m,   1),
            "max_velocity_mps": round(r.max_velocity_mps, 1),
            "flight_time_s":    round(r.flight_time_s,    2),
            "score":            round(r.stability_score,  2),
            "error":            r.error or "",
        }
        # Achata params e launch
        for k, v in r.params.items():
            row[f"p_{k}"] = round(v, 4)
        for k, v in r.launch.items():
            row[f"l_{k}"] = round(v, 3)
        rows.append(row)

    df = pd.DataFrame(rows)
    return df


def print_report(df: pd.DataFrame, base_values: dict, top_n: int = 10):
    valid = df[df["error"] == ""].copy()
    if valid.empty:
        print("\n[!] Nenhuma simulação concluiu sem erro.")
        return

    top = valid.nlargest(top_n, "score")
    best = top.iloc[0]

    SEP = "═" * 62

    print(f"\n{SEP}")
    print("  ANÁLISE MONTE CARLO — OPENROCKET")
    print(SEP)
    print(f"  Total de simulações : {len(df)}")
    print(f"  Simulações válidas  : {len(valid)}")
    print(f"  Taxa de erro        : {(1 - len(valid)/len(df))*100:.1f}%")

    print(f"\n{'─'*62}")
    print("  DISTRIBUIÇÃO DE ESTABILIDADE")
    print(f"{'─'*62}")
    print(f"  Instáveis (< {STABILITY_MIN})    : {(valid['stability_margin'] < STABILITY_MIN).sum()}")
    print(f"  Ideais ({STABILITY_IDEAL_LOW}–{STABILITY_IDEAL_HIGH})   : "
          f"{((valid['stability_margin'] >= STABILITY_IDEAL_LOW) & (valid['stability_margin'] <= STABILITY_IDEAL_HIGH)).sum()}")
    print(f"  Superdominantes (> 3.0) : {(valid['stability_margin'] > 3.0).sum()}")

    print(f"\n{'─'*62}")
    print(f"  🏆 MELHOR DESIGN  (run #{int(best['run_id'])})")
    print(f"{'─'*62}")
    print(f"  Score             : {best['score']:.2f} / 100")
    print(f"  Estabilidade      : {best['stability_margin']:.3f} cal")
    print(f"  Altitude máx.     : {best['max_altitude_m']:.1f} m")
    print(f"  Velocidade máx.   : {best['max_velocity_mps']:.1f} m/s")
    print(f"  Tempo de voo      : {best['flight_time_s']:.2f} s")

    print(f"\n  Parâmetros (fatores sobre base):")
    for col in [c for c in best.index if c.startswith("p_")]:
        name = col[2:]
        base_key = name if name in base_values else name
        factor   = best[col]
        base_v   = base_values.get(base_key, 1.0)
        abs_v    = base_v * factor
        print(f"    {name:<22} factor={factor:.4f}  abs={abs_v:.4f}")

    print(f"\n  Condições de lançamento:")
    for col in [c for c in best.index if c.startswith("l_")]:
        print(f"    {col[2:]:<22} {best[col]:.3f}")

    print(f"\n{'─'*62}")
    print(f"  TOP {top_n} DESIGNS (por score)")
    print(f"{'─'*62}")
    display_cols = ["run_id", "score", "stability_margin",
                    "max_altitude_m", "max_velocity_mps"]
    print(top[display_cols].to_string(index=False))
    print(f"\n{SEP}\n")


def export(df: pd.DataFrame, path: Path):
    df.to_csv(path, index=False)
    print(f"  Resultados exportados → {path}")

    best_params_path = path.with_suffix(".best.json")
    valid = df[df["error"] == ""]
    if not valid.empty:
        best = valid.loc[valid["score"].idxmax()].to_dict()
        best_params_path.write_text(json.dumps(best, indent=2))
        print(f"  Melhor design exportado → {best_params_path}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Monte Carlo para OpenRocket via JPype"
    )
    parser.add_argument("--runs",    type=int,  default=1000,
                        help="Número de simulações (padrão: 1000)")
    parser.add_argument("--seed",    type=int,  default=42,
                        help="Seed aleatória (padrão: 42)")
    parser.add_argument("--top",     type=int,  default=10,
                        help="Quantos melhores exibir (padrão: 10)")
    parser.add_argument("--output",  type=str,  default="montecarlo_results.csv",
                        help="Arquivo de saída CSV")
    parser.add_argument("--jar",     type=str,  default=str(OPENROCKET_JAR),
                        help="Caminho para o JAR do OpenRocket")
    parser.add_argument("--ork",     type=str,  default=str(ROCKET_ORK),
                        help="Caminho para o arquivo .ork base")
    args = parser.parse_args()

    jar = Path(args.jar)
    ork = Path(args.ork)

    # 1. JVM
    start_jvm(jar)

    # 2. OpenRocket Application
    init_openrocket()

    # 3. Carrega foguete base
    doc, rocket = load_rocket(ork)
    base_values  = read_base_values(rocket)

    print("\n  Parâmetros base lidos do .ork:")
    for k, v in base_values.items():
        print(f"    {k:<30} {v:.5f}")

    # 4. Monte Carlo
    results = monte_carlo(
        n_runs=args.runs,
        doc=doc,
        rocket=rocket,
        base_values=base_values,
        seed=args.seed,
    )

    # 5. Análise
    df = analyze(results)
    print_report(df, base_values, top_n=args.top)

    # 6. Exporta
    export(df, Path(args.output))

    # 7. Shutdown JVM
    import jpype
    jpype.shutdownJVM()
    print("  JVM encerrada. Fim.")


if __name__ == "__main__":
    main()