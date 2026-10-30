# Checklist 100% — Steam

## Como rodar
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env  (e edite o arquivo)
uvicorn main:app --reload
```
Abra http://127.0.0.1:8000

## Cadastrar um "como conseguir"
```bash
curl -X POST http://127.0.0.1:8000/api/guia \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: SUA_SENHA_DO_ENV" \
  -d '{"appid":292030,"api_name":"NOME_API_DA_CONQUISTA","texto":"Passo a passo...","fase":"Campanha","tags":"perdível, missão"}'
```
O `api_name` de cada conquista aparece na resposta de `/api/jogo/<appid>` (campo `id`).

## Estrutura
- `main.py`: backend (Steam + cache SQLite + guias)
- `frontend/`: site (HTML, CSS, JS)
- `dados.db`: criado sozinho na primeira execução
