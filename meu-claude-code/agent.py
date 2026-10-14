#!/usr/bin/env python3
"""meu-claude-code: agente de código no terminal, 100% grátis (Gemini API, camada gratuita).

O agente trabalha na pasta de onde você o executa (como o Claude Code):
lê, cria e edita arquivos, busca texto e roda comandos. Ações que alteram
algo (escrever, editar, rodar comando) pedem a sua confirmação.
"""

import difflib
import fnmatch
import os
import platform
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------

DEFAULT_MODEL = "gemini-3.8-flash"  # troque no .env (MODEL=...) ou com /modelo
MAX_STEPS = 30          # máximo de chamadas de ferramenta por mensagem sua
MAX_READ_CHARS = 40_000
MAX_CMD_CHARS = 8_000
MAX_LIST = 300
MAX_MATCHES = 100
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}

ROOT = Path.cwd().resolve()   # pasta de trabalho do agente
AUTO_APPROVE = False          # /auto liga/desliga a aprovação automática

if os.name == "nt":
    os.system("")  # habilita cores ANSI no terminal do Windows


def _color(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def dim(t): return _color("2", t)
def red(t): return _color("31", t)
def green(t): return _color("32", t)
def yellow(t): return _color("33", t)
def cyan(t): return _color("36", t)
def bold(t): return _color("1", t)


def load_env() -> None:
    """Lê um arquivo .env simples (pasta do agente e pasta atual)."""
    for base in (Path(__file__).resolve().parent, Path.cwd()):
        env_file = base / ".env"
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

try:
    from google import genai
    from google.genai import errors, types
except ImportError:
    sys.exit(red("Falta instalar a dependência. Rode: pip install -r requirements.txt"))


# --------------------------------------------------------------------------
# Utilidades das ferramentas
# --------------------------------------------------------------------------

def _resolve(path: str) -> Path:
    """Resolve um caminho garantindo que ele fique dentro da pasta de trabalho."""
    p = (ROOT / path).resolve()
    if p != ROOT and not p.is_relative_to(ROOT):
        raise ValueError(f"'{path}' está fora da pasta de trabalho ({ROOT}).")
    return p


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT)) or "."
    except ValueError:
        return str(p)


def _log(text: str) -> None:
    print(dim(f"  ⚙ {text}"))


def _is_binary(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            return b"\0" in f.read(2048)
    except OSError:
        return True


def _confirm(question: str) -> bool:
    """Pergunta s/N. Responder 'a' libera tudo até o fim da sessão."""
    global AUTO_APPROVE
    if AUTO_APPROVE:
        return True
    try:
        ans = input(yellow(f"  ? {question} [s/N/a=sempre] ")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if ans in ("a", "sempre", "all"):
        AUTO_APPROVE = True
        print(dim("  (aprovação automática ligada; use /auto para desligar)"))
        return True
    return ans in ("s", "sim", "y", "yes")


def _diff(old: str, new: str, name: str, limit: int = 60) -> str:
    lines = []
    for line in difflib.unified_diff(
        old.splitlines(), new.splitlines(), f"a/{name}", f"b/{name}", lineterm="", n=2
    ):
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(green(line))
        elif line.startswith("-") and not line.startswith("---"):
            lines.append(red(line))
        elif line.startswith("@@"):
            lines.append(cyan(line))
        else:
            lines.append(dim(line))
    if len(lines) > limit:
        lines = lines[:limit] + [dim(f"... (+{len(lines) - limit} linhas no diff)")]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Ferramentas (o modelo chama estas funções)
# Os docstrings e type hints viram a descrição que o modelo enxerga.
# --------------------------------------------------------------------------

def list_files(path: str = ".", recursive: bool = False) -> str:
    """Lista arquivos e pastas de um diretório (pastas terminam com '/').

    Args:
        path: diretório a listar, relativo à pasta de trabalho. Padrão: ".".
        recursive: se True, lista todos os arquivos das subpastas também.
    """
    _log(f"list_files({path!r}, recursive={recursive})")
    try:
        base = _resolve(path)
        if not base.is_dir():
            return f"Erro: '{path}' não é uma pasta."
        linhas = []
        if recursive:
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS)
                for f in sorted(filenames):
                    linhas.append(_rel(Path(dirpath) / f))
                if len(linhas) >= MAX_LIST:
                    linhas = linhas[:MAX_LIST] + ["... (lista cortada)"]
                    break
        else:
            itens = sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            for item in itens:
                if item.name in IGNORE_DIRS:
                    continue
                linhas.append(item.name + ("/" if item.is_dir() else ""))
        return "\n".join(linhas) or "(pasta vazia)"
    except Exception as e:
        return f"Erro: {e}"


def read_file(path: str, start_line: int = 1, end_line: int = 0) -> str:
    """Lê um arquivo de texto e devolve o conteúdo com números de linha.

    Args:
        path: caminho do arquivo, relativo à pasta de trabalho.
        start_line: primeira linha a ler (começa em 1).
        end_line: última linha a ler; 0 significa até o final do arquivo.
    """
    _log(f"read_file({path!r}, {start_line}, {end_line})")
    try:
        p = _resolve(path)
        if not p.is_file():
            return f"Erro: '{path}' não existe ou não é um arquivo."
        if _is_binary(p):
            return f"Erro: '{path}' parece ser um arquivo binário."
        linhas = p.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(linhas)
        ini = max(int(start_line), 1)
        fim = int(end_line) if int(end_line) > 0 else total
        trecho = linhas[ini - 1:fim]
        saida = "\n".join(f"{i}\t{l}" for i, l in enumerate(trecho, start=ini))
        if len(saida) > MAX_READ_CHARS:
            saida = saida[:MAX_READ_CHARS] + "\n... (cortado; use start_line/end_line para ver o resto)"
        return f"[{_rel(p)}: {total} linhas]\n{saida}"
    except Exception as e:
        return f"Erro: {e}"


def write_file(path: str, content: str) -> str:
    """Cria um arquivo novo ou sobrescreve um existente com o conteúdo completo.
    Para mudar só um trecho de um arquivo que já existe, prefira edit_file.

    Args:
        path: caminho do arquivo, relativo à pasta de trabalho.
        content: conteúdo completo do arquivo.
    """
    _log(f"write_file({path!r}, {len(content)} caracteres)")
    try:
        p = _resolve(path)
        if p.is_dir():
            return f"Erro: '{path}' é uma pasta."
        if p.exists():
            antigo = p.read_text(encoding="utf-8", errors="replace")
            print(f"  Sobrescrever {bold(_rel(p))}:")
            print(_diff(antigo, content, _rel(p)))
        else:
            print(f"  Criar {bold(_rel(p))}:")
            preview = content.splitlines()[:20]
            print(green("\n".join("+ " + l for l in preview)))
            if len(content.splitlines()) > 20:
                print(dim(f"  ... (+{len(content.splitlines()) - 20} linhas)"))
        if not _confirm("Aplicar?"):
            return "O usuário negou a escrita do arquivo."
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"OK: {_rel(p)} salvo ({len(content)} caracteres)."
    except Exception as e:
        return f"Erro: {e}"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Troca um trecho exato de um arquivo existente por outro. O trecho
    old_text precisa aparecer exatamente uma vez (inclua linhas vizinhas
    para torná-lo único). Leia o arquivo antes com read_file.

    Args:
        path: caminho do arquivo, relativo à pasta de trabalho.
        old_text: trecho atual a ser substituído (copie exatamente, com indentação).
        new_text: texto novo que entra no lugar.
    """
    _log(f"edit_file({path!r})")
    try:
        p = _resolve(path)
        if not p.is_file():
            return f"Erro: '{path}' não existe. Use write_file para criar."
        texto = p.read_text(encoding="utf-8")
        vezes = texto.count(old_text)
        if vezes == 0:
            return "Erro: old_text não foi encontrado. Releia o arquivo e copie o trecho exatamente."
        if vezes > 1:
            return f"Erro: old_text aparece {vezes} vezes. Inclua mais linhas ao redor para torná-lo único."
        novo = texto.replace(old_text, new_text, 1)
        print(f"  Editar {bold(_rel(p))}:")
        print(_diff(texto, novo, _rel(p)))
        if not _confirm("Aplicar?"):
            return "O usuário negou a edição."
        p.write_text(novo, encoding="utf-8")
        return f"OK: {_rel(p)} editado."
    except Exception as e:
        return f"Erro: {e}"


def search_text(pattern: str, path: str = ".", file_glob: str = "*") -> str:
    """Busca texto (expressão regular) dentro dos arquivos, como o grep.
    Devolve linhas no formato 'arquivo:linha: texto'.

    Args:
        pattern: expressão regular a procurar (sem diferenciar maiúsculas).
        path: pasta ou arquivo onde procurar. Padrão: ".".
        file_glob: filtra pelo nome do arquivo, ex.: "*.py". Padrão: todos.
    """
    _log(f"search_text({pattern!r}, {path!r}, {file_glob!r})")
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        base = _resolve(path)
        if base.is_file():
            arquivos = [base]
        else:
            arquivos = []
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS)
                for f in sorted(filenames):
                    if fnmatch.fnmatch(f, file_glob):
                        arquivos.append(Path(dirpath) / f)
        achados = []
        for arq in arquivos:
            try:
                if arq.stat().st_size > 1_000_000 or _is_binary(arq):
                    continue
                with open(arq, encoding="utf-8", errors="replace") as fh:
                    for n, linha in enumerate(fh, start=1):
                        if regex.search(linha):
                            achados.append(f"{_rel(arq)}:{n}: {linha.rstrip()[:200]}")
                            if len(achados) >= MAX_MATCHES:
                                achados.append("... (resultados cortados)")
                                return "\n".join(achados)
            except OSError:
                continue
        return "\n".join(achados) or "Nenhum resultado."
    except re.error as e:
        return f"Erro: regex inválida ({e})."
    except Exception as e:
        return f"Erro: {e}"


def run_command(command: str, timeout_seconds: int = 60) -> str:
    """Executa um comando no terminal, na pasta de trabalho, e devolve a saída
    (stdout + stderr) e o código de saída. O comando não pode ser interativo
    (não pode esperar digitação). Sempre pede confirmação ao usuário.

    Args:
        command: comando de shell a executar.
        timeout_seconds: tempo máximo de execução em segundos. Padrão: 60.
    """
    _log(f"run_command({command!r})")
    print(f"  Comando: {bold(command)}")
    if not _confirm("Executar?"):
        return "O usuário negou a execução do comando."
    try:
        r = subprocess.run(
            command,
            shell=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout_seconds)),
            stdin=subprocess.DEVNULL,
        )
        saida = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        if len(saida) > MAX_CMD_CHARS:
            saida = saida[:MAX_CMD_CHARS] + "\n... (saída cortada)"
        print(dim(saida.rstrip()[:1500] or "  (sem saída)"))
        return f"código de saída: {r.returncode}\n{saida}"
    except subprocess.TimeoutExpired:
        return f"Erro: o comando passou de {timeout_seconds}s e foi interrompido."
    except Exception as e:
        return f"Erro: {e}"


TOOL_FUNCS = [list_files, read_file, write_file, edit_file, search_text, run_command]
TOOLS_BY_NAME = {f.__name__: f for f in TOOL_FUNCS}


def execute_tool(name: str, args: dict) -> str:
    fn = TOOLS_BY_NAME.get(name)
    if fn is None:
        return f"Erro: ferramenta '{name}' não existe."
    try:
        return str(fn(**args))
    except TypeError as e:
        return f"Erro nos argumentos de {name}: {e}"
    except Exception as e:
        return f"Erro ao executar {name}: {e}"


# --------------------------------------------------------------------------
# Loop do agente
# --------------------------------------------------------------------------

def build_system_prompt() -> str:
    return (
        "Você é um agente de programação que roda no terminal do usuário, "
        "parecido com o Claude Code. Ajude a ler, entender, criar e editar "
        "projetos de código usando as ferramentas disponíveis.\n\n"
        f"Pasta de trabalho: {ROOT}\n"
        f"Sistema operacional: {platform.system()} ({platform.release()})\n"
        f"Data de hoje: {date.today().isoformat()}\n\n"
        "Regras:\n"
        "- Responda em português, de forma direta e curta.\n"
        "- Antes de editar um arquivo, leia-o com read_file. Para mudar um trecho use "
        "edit_file; use write_file só para arquivos novos ou reescritas completas.\n"
        "- Se não souber onde algo está, use list_files e search_text antes de chutar.\n"
        "- Use run_command para rodar testes, instalar dependências ou executar scripts. "
        "Comandos devem ser compatíveis com o sistema operacional acima e não podem ser interativos.\n"
        "- Faça passos pequenos e, ao terminar, diga em 1 ou 2 frases o que mudou.\n"
        "- Se o usuário negar uma ação, não insista: pergunte como ele prefere seguir."
    )


def make_config() -> "types.GenerateContentConfig":
    return types.GenerateContentConfig(
        system_instruction=build_system_prompt(),
        tools=TOOL_FUNCS,
        temperature=0.3,
        # Nós mesmos executamos as ferramentas (para pedir confirmação e tratar erros).
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


def list_models(client) -> list:
    nomes = []
    for m in client.models.list():
        acoes = getattr(m, "supported_actions", None) or []
        if "generateContent" in acoes:
            nomes.append((m.name or "").replace("models/", ""))
    return sorted(nomes)


def call_api(client, model: str, history: list, config):
    """Chama o modelo com novas tentativas para limite de uso (429) e instabilidade."""
    for tentativa in range(5):
        try:
            return client.models.generate_content(model=model, contents=history, config=config)
        except errors.APIError as e:
            codigo = getattr(e, "code", None)
            if codigo in (429, 500, 502, 503, 504) and tentativa < 4:
                espera = min(8 * (2 ** tentativa), 60)
                motivo = "limite grátis atingido" if codigo == 429 else "API instável"
                print(dim(f"  ⏳ {motivo} ({codigo}). Nova tentativa em {espera}s..."))
                time.sleep(espera)
                continue
            raise


def run_turn(client, model: str, history: list, config, user_text: str) -> None:
    """Processa uma mensagem do usuário, executando ferramentas até o modelo responder."""
    marca = len(history)
    history.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
    try:
        for _ in range(MAX_STEPS):
            resp = call_api(client, model, history, config)
            cand = resp.candidates[0] if resp.candidates else None
            if cand is None or cand.content is None or not cand.content.parts:
                motivo = getattr(cand, "finish_reason", None) if cand else "sem resposta"
                print(yellow(f"(O modelo devolveu uma resposta vazia: {motivo}. Tente reformular.)"))
                return
            history.append(cand.content)  # mantém tudo, inclusive assinaturas de raciocínio

            texto = "".join(
                p.text for p in cand.content.parts if p.text and not getattr(p, "thought", False)
            )
            if texto.strip():
                print(f"\n{texto.strip()}")

            chamadas = [p.function_call for p in cand.content.parts if p.function_call]
            if not chamadas:
                return

            respostas = []
            for fc in chamadas:
                resultado = execute_tool(fc.name, dict(fc.args or {}))
                respostas.append(
                    types.Part.from_function_response(name=fc.name, response={"result": resultado})
                )
            history.append(types.Content(role="user", parts=respostas))
        print(yellow(f"\n(Parei após {MAX_STEPS} passos. Diga 'continue' se quiser seguir.)"))
    except KeyboardInterrupt:
        del history[marca:]
        print(yellow("\n(Cancelado. Essa mensagem foi descartada do histórico.)"))
    except errors.APIError as e:
        del history[marca:]
        codigo = getattr(e, "code", None)
        if codigo == 404:
            print(red(f"\nModelo '{model}' não encontrado."))
            try:
                flash = [n for n in list_models(client) if "flash" in n]
                print("Modelos disponíveis (flash):\n  " + "\n  ".join(flash[:15]))
            except Exception:
                pass
            print("Troque com /modelo NOME ou defina MODEL=NOME no arquivo .env")
        elif codigo in (400, 401, 403) and "API key" in str(e):
            print(red("\nChave de API inválida. Confira GEMINI_API_KEY no arquivo .env."))
        elif codigo == 429:
            print(red("\nLimite da camada grátis estourado mesmo após novas tentativas. Espere um pouco e tente de novo."))
        else:
            print(red(f"\nErro da API ({codigo}): {e}"))


# --------------------------------------------------------------------------
# Interface (REPL)
# --------------------------------------------------------------------------

HELP = """Comandos:
  /ajuda          mostra esta ajuda
  /clear          limpa o histórico da conversa
  /auto           liga/desliga a aprovação automática de ações
  /modelo [nome]  mostra ou troca o modelo
  /modelos        lista os modelos disponíveis na sua chave
  /sair           encerra
Termine uma linha com \\ para continuar escrevendo na linha seguinte."""


def read_input() -> str:
    linhas = []
    prompt = bold(cyan("\n> "))
    while True:
        linha = input(prompt if not linhas else dim("… "))
        if linha.endswith("\\"):
            linhas.append(linha[:-1])
            continue
        linhas.append(linha)
        return "\n".join(linhas).strip()


def main() -> None:
    global AUTO_APPROVE
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        sys.exit(
            red("Defina a variável GEMINI_API_KEY (copie .env.example para .env e cole sua chave).\n")
            + "Chave grátis em: https://aistudio.google.com/apikey"
        )

    client = genai.Client(api_key=api_key)
    model = os.environ.get("MODEL", DEFAULT_MODEL)
    config = make_config()
    history: list = []

    print(bold("meu-claude-code") + dim(f"  •  modelo: {model}  •  pasta: {ROOT}"))
    print(dim("Digite /ajuda para ver os comandos. Ctrl+C cancela a resposta atual."))

    while True:
        try:
            entrada = read_input()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not entrada:
            continue

        if entrada.startswith("/"):
            cmd, _, arg = entrada.partition(" ")
            cmd = cmd.lower()
            if cmd in ("/sair", "/exit", "/quit"):
                break
            elif cmd == "/ajuda":
                print(HELP)
            elif cmd == "/clear":
                history.clear()
                print(dim("Histórico limpo."))
            elif cmd == "/auto":
                AUTO_APPROVE = not AUTO_APPROVE
                print(dim(f"Aprovação automática: {'LIGADA' if AUTO_APPROVE else 'desligada'}"))
            elif cmd == "/modelo":
                if arg.strip():
                    model = arg.strip()
                print(dim(f"Modelo atual: {model}"))
            elif cmd == "/modelos":
                try:
                    print("\n".join(list_models(client)))
                except errors.APIError as e:
                    print(red(f"Erro ao listar modelos: {e}"))
            else:
                print(yellow("Comando desconhecido. Use /ajuda."))
            continue

        run_turn(client, model, history, config, entrada)

    print(dim("Até mais!"))


if __name__ == "__main__":
    main()
