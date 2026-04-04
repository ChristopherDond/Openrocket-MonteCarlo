# OpenRocket Monte Carlo

**[Versão em inglês](README.md)**

Ferramenta em Python para executar experimentos de Monte Carlo com projetos do OpenRocket.

## O que há no repositório
- `openrocket_montecarlo.py`: script principal
- `base_rocket.ork`: design de exemplo do OpenRocket
- `OpenRocket-15.03.jar`: runtime do OpenRocket (usado pelo script)
- `settings.json`: configuração de exemplo
- `test_jpype.py`: teste rápido do JPype

## Requisitos
- Python 3.8+
- JPype
- Java (necessário para o OpenRocket)

## Início rápido
1. Garanta que o Java esteja instalado e no PATH.
2. Instale as dependências Python:
   - `pip install jpype1`
3. Execute:
   - `python openrocket_montecarlo.py`

## Observações
- Ajuste o `settings.json` conforme suas entradas de simulação.
- O script espera o JAR do OpenRocket no repositório.
