# meu-claude-code

Agente de código no terminal, no estilo Claude Code, **100% grátis** (usa a camada gratuita da API do Gemini, sem cartão).

O agente trabalha na pasta de onde você o executa: lê arquivos, cria e edita arquivos (mostrando o diff), busca texto e roda comandos. Tudo que altera algo pede a sua confirmação.

## Instalar

1. Pegue uma chave grátis em https://aistudio.google.com/apikey
2. Rode a instalação:
   - Linux/macOS: `bash setup.sh`
   - Windows: `setup.bat`
3. Abra o arquivo `.env` que foi criado e cole a chave em `GEMINI_API_KEY`.

## Usar

Entre na pasta do **seu projeto** e rode o agente por lá:

```bash
cd ~/meu-projeto
/caminho/para/meu-claude-code/run.sh        # Windows: C:\caminho\meu-claude-code\run.bat
```

Dica: coloque a pasta `meu-claude-code` no PATH (ou crie um alias) para chamar de qualquer lugar.

Exemplos de pedidos:

- `liste os arquivos e me explique o que esse projeto faz`
- `crie um arquivo hello.py que imprime os 10 primeiros primos e rode ele`
- `ache onde a função login é usada e renomeie para sign_in`

## Comandos

| Comando | O que faz |
|---|---|
| `/ajuda` | lista os comandos |
| `/clear` | limpa o histórico da conversa |
| `/auto` | liga/desliga aprovação automática de ações |
| `/modelo [nome]` | mostra ou troca o modelo |
| `/modelos` | lista os modelos disponíveis na sua chave |
| `/sair` | encerra |

Ao confirmar uma ação, responder `a` libera tudo até o fim da sessão. `Ctrl+C` cancela a resposta atual.

## Ferramentas do agente

`list_files`, `read_file`, `write_file`, `edit_file` (troca de trecho com diff), `search_text` (regex, tipo grep) e `run_command` (sempre com confirmação).

As ferramentas de arquivo só enxergam a pasta onde o agente foi iniciado.

## Limites da camada grátis

O Gemini grátis tem limite de requisições por minuto e por dia, e cada chamada de ferramenta conta como uma requisição. Se estourar, o agente espera e tenta de novo sozinho. Para trocar de modelo: `/modelos` e depois `/modelo NOME`.

Se quiser **sem limite nenhum**, dá para trocar o Gemini por um modelo local com o Ollama (precisa de um computador razoável).

## Segurança

- `run_command` executa comandos de verdade na sua máquina: leia antes de aprovar.
- Evite o modo `/auto` em pastas importantes.
- Não suba o arquivo `.env` para o GitHub (já está no `.gitignore`).
