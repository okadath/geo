"""Lanzador delgado del servidor web de tecto (FastAPI + Uvicorn).

La logica vive en el paquete servidor/ (app en servidor.app:app). Este archivo
solo parsea flags y arranca uvicorn. La autorecarga la hace uvicorn (vigila los
*.py del proyecto), en reemplazo del viejo _vigilar_cambios.

Uso:
    python3 web.py [-p PUERTO] [--host HOST] [--sin-recarga]

Comodidad: si existe .venv/ y NO estamos ya dentro, este script se re-ejecuta
con .venv/bin/python (os.execv), de modo que `python3 web.py` funciona a secas
sin activar el entorno a mano. El servidor escucha solo en 127.0.0.1 por
defecto; los resultados van a salidas/ (fuera de git).
"""
import argparse
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent


def _reejecutar_en_venv():
    """Si hay .venv/ y no la estamos usando, re-lanza con su python (execv).

    Asi `python3 web.py` toma las dependencias del entorno sin activarlo.
    Se hace ANTES de importar uvicorn (que vive en la .venv)."""
    venv = BASE / ".venv"
    venv_py = venv / "bin" / "python"
    if not venv_py.exists():
        return
    # ¿ya estamos usando la .venv? Comparar por sys.prefix, NO por el ejecutable:
    # .venv/bin/python es un symlink al python del sistema, asi que resolverlo
    # daria un falso positivo (pareceria que ya estamos dentro).
    if Path(sys.prefix).resolve() == venv.resolve():
        return
    # bandera anti-bucle por si el resolve() difiere de forma inesperada
    if os.environ.get("TECTO_REEXEC") == "1":
        return
    os.environ["TECTO_REEXEC"] = "1"
    os.execv(str(venv_py), [str(venv_py), str(BASE / "web.py"), *sys.argv[1:]])


def main():
    p = argparse.ArgumentParser(description="Servidor web local de tecto (FastAPI)")
    p.add_argument("-p", "--puerto", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1",
                   help="interfaz de escucha (por defecto 127.0.0.1)")
    p.add_argument("--sin-recarga", action="store_true",
                   help="no reiniciar automaticamente al cambiar los .py")
    args = p.parse_args()

    import uvicorn   # se importa despues del posible re-exec a la .venv

    (BASE / "salidas").mkdir(exist_ok=True)
    recarga = not args.sin_recarga
    print(f"tecto web -> http://{args.host}:{args.puerto}  (Ctrl+C para salir)")
    uvicorn.run(
        "servidor.app:app",
        host=args.host,
        port=args.puerto,
        reload=recarga,
        # uvicorn reemplaza al viejo _vigilar_cambios: vigila los *.py del
        # proyecto y reinicia al cambiarlos (los *_srv.py se importan al
        # arrancar, asi que editar uno requiere reiniciar; esto lo hace solo)
        reload_dirs=[str(BASE)] if recarga else None,
        reload_includes=["*.py"] if recarga else None,
        log_level="warning",
    )


if __name__ == "__main__":
    _reejecutar_en_venv()
    main()
