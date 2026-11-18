"""Transporta .env cifrado con Fernet; la clave nunca se imprime ni se sube a Git."""
import argparse
import os
from pathlib import Path
import tempfile

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parent


def write_atomic(path, content, overwrite=False):
    """Escribe en el mismo directorio; no deja un .env parcialmente restaurado."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError('El destino ya existe; usa --force para reemplazarlo.')
    fd, name = tempfile.mkstemp(prefix='.portable-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        if overwrite:
            os.replace(name, path)
        elif os.name == 'nt':
            # Windows no reemplaza un destino existente con os.rename.
            os.rename(name, path)
        else:
            # Crear el nombre final sin reemplazar si otro proceso lo creó.
            os.link(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def seal(env_file, key_file, output_file, overwrite=False):
    env_file, key_file, output_file = map(Path, (env_file, key_file, output_file))
    if len({p.resolve() for p in (env_file, key_file, output_file)}) != 3:
        raise ValueError('El .env, la clave y el archivo cifrado deben tener rutas distintas.')
    if output_file.exists() and not overwrite:
        raise FileExistsError('El archivo cifrado ya existe; usa --force para actualizarlo.')
    original = env_file.read_bytes()
    if not key_file.exists():
        write_atomic(key_file, Fernet.generate_key() + b'\n')
    cipher = Fernet(key_file.read_bytes().strip())
    token = cipher.encrypt(original)
    if cipher.decrypt(token) != original:
        raise ValueError('No se pudo verificar el cifrado.')
    write_atomic(output_file, token + b'\n', overwrite)


def restore(encrypted_file, key_file, env_file, overwrite=False):
    encrypted_file, key_file, env_file = map(Path, (encrypted_file, key_file, env_file))
    if len({p.resolve() for p in (encrypted_file, key_file, env_file)}) != 3:
        raise ValueError('El archivo cifrado, la clave y el .env deben tener rutas distintas.')
    if env_file.exists() and not overwrite:
        raise FileExistsError('Ya existe un .env local; se conserva. Usa --force si quieres reemplazarlo.')
    # Verifica autenticidad antes de crear o modificar el .env.
    original = Fernet(key_file.read_bytes().strip()).decrypt(encrypted_file.read_bytes().strip())
    write_atomic(env_file, original, overwrite)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Cifrar o restaurar .env sin mostrar credenciales')
    commands = parser.add_subparsers(dest='command', required=True)
    encrypt = commands.add_parser('cifrar', help='Crea una copia cifrada y una clave si no existe')
    encrypt.add_argument('--env-file', type=Path, default=ROOT / '.env')
    encrypt.add_argument('--key-file', type=Path, required=True)
    encrypt.add_argument('--output', type=Path, default=ROOT / '.env.enc')
    encrypt.add_argument('--force', action='store_true')
    decrypt = commands.add_parser('restaurar', help='Recupera el .env local con la clave privada')
    decrypt.add_argument('--encrypted-file', type=Path, default=ROOT / '.env.enc')
    decrypt.add_argument('--key-file', type=Path, required=True)
    decrypt.add_argument('--output', type=Path, default=ROOT / '.env')
    decrypt.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'cifrar':
            seal(args.env_file, args.key_file, args.output, args.force)
            print('Copia cifrada y verificada. Guarda la clave fuera de Git y transportala en privado.')
        else:
            restore(args.encrypted_file, args.key_file, args.output, args.force)
            print('.env restaurado. No se iniciaron contactos ni se crearon tareas.')
        return 0
    except InvalidToken:
        print('No se pudo descifrar: clave incorrecta o archivo alterado. El .env no se modifico.')
    except (OSError, ValueError):
        # No incluir valores de claves, tokens ni datos del archivo en los errores.
        print('No se pudo completar: revisa las rutas, la clave y los permisos. Si el destino existe, se conserva salvo --force.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
