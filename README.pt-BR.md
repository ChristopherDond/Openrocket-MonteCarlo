# OpenRocket Monte Carlo

**[Versão em inglês](README.md)**

Ferramenta em Python para executar experimentos de Monte Carlo com projetos do OpenRocket.

## O que há no repositório
- `src/openrocket_montecarlo.py`: script principal
- `assets/base_rocket.ork`: design de exemplo do OpenRocket
- `assets/OpenRocket-15.03.jar`: runtime do OpenRocket (usado pelo script)
- `settings.json`: configuração de exemplo
- `tests/test_jpype.py`: teste rápido do JPype

## Requisitos
- Python 3.8+
- JPype
- Java (necessário para o OpenRocket)

## Início rápido
1. Garanta que o Java esteja instalado e no PATH.
2. Instale as dependências Python:
   - `pip install jpype1`
3. Execute:
   - `python src/openrocket_montecarlo.py`

## Observações
- Ajuste o `settings.json` conforme suas entradas de simulação.
- O script espera o JAR do OpenRocket em `assets/`.
