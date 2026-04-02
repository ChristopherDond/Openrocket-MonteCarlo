# OpenRocket Monte Carlo

**[English Version](README.md)**

Ferramenta em Python para executar experimentos de Monte Carlo com projetos do OpenRocket.

## O que ha no repositorio
- `openrocket_montecarlo.py`: script principal
- `base_rocket.ork`: design de exemplo do OpenRocket
- `OpenRocket-15.03.jar`: runtime do OpenRocket (usado pelo script)
- `settings.json`: configuracao de exemplo
- `test_jpype.py`: teste rapido do JPype

## Requisitos
- Python 3.8+
- JPype
- Java (necessario para o OpenRocket)

## Inicio rapido
1. Garanta que o Java esteja instalado e no PATH.
2. Instale as dependencias Python:
   - `pip install jpype1`
3. Execute:
   - `python openrocket_montecarlo.py`

## Observacoes
- Ajuste o `settings.json` conforme suas entradas de simulacao.
- O script espera o JAR do OpenRocket no repositorio.
