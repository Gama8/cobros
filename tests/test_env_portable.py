"""Pruebas con configuraciones inventadas; sin proveedores ni credenciales reales."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import SkipTest, TestCase

try:
    from cryptography.fernet import Fernet, InvalidToken
    from env_portable import restore, seal
except ImportError as exc:
    raise SkipTest('Instala requirements-env.txt para probar la configuracion cifrada.') from exc


class PortableEnvTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.env'
        self.key = self.root / 'private' / 'env.key'
        self.token = self.root / '.env.enc'
        self.destination = self.root / 'other-pc' / '.env'
        self.original = b'# prueba\r\nTEST_PHONE=+570000000000\r\nDRY_RUN=true\r\n'
        self.source.write_bytes(self.original)

    def test_roundtrip_keeps_exact_bytes_and_reuses_key(self):
        seal(self.source, self.key, self.token)
        key = self.key.read_bytes()
        self.assertNotIn(self.original, self.token.read_bytes())
        restore(self.token, self.key, self.destination)
        self.assertEqual(self.destination.read_bytes(), self.original)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.source.write_bytes(b'DRY_RUN=false\n')
        seal(self.source, self.key, self.token, overwrite=True)
        self.assertEqual(self.key.read_bytes(), key)
        restore(self.token, self.key, self.destination, overwrite=True)
        self.assertEqual(self.destination.read_bytes(), b'DRY_RUN=false\n')

    def test_existing_env_is_preserved_by_default(self):
        seal(self.source, self.key, self.token)
        self.destination.parent.mkdir()
        self.destination.write_bytes(b'KEEP=local\n')
        with self.assertRaises(FileExistsError):
            restore(self.token, self.key, self.destination)
        self.assertEqual(self.destination.read_bytes(), b'KEEP=local\n')

    def test_wrong_key_does_not_create_plaintext(self):
        seal(self.source, self.key, self.token)
        other_key = self.root / 'wrong.key'
        other_key.write_bytes(Fernet.generate_key())
        with self.assertRaises(InvalidToken):
            restore(self.token, other_key, self.destination)
        self.assertFalse(self.destination.exists())

    def test_altered_ciphertext_does_not_replace_existing_env(self):
        seal(self.source, self.key, self.token)
        token = bytearray(self.token.read_bytes().strip())
        token[len(token) // 2] = ord('A') if token[len(token) // 2] != ord('A') else ord('B')
        self.token.write_bytes(token)
        self.destination.parent.mkdir()
        self.destination.write_bytes(b'KEEP=local\n')
        with self.assertRaises(InvalidToken):
            restore(self.token, self.key, self.destination, overwrite=True)
        self.assertEqual(self.destination.read_bytes(), b'KEEP=local\n')

    def test_ciphertext_is_not_replaced_without_force(self):
        seal(self.source, self.key, self.token)
        original_token = self.token.read_bytes()
        with self.assertRaises(FileExistsError):
            seal(self.source, self.key, self.token)
        self.assertEqual(self.token.read_bytes(), original_token)

    def test_conflicting_paths_are_rejected(self):
        with self.assertRaises(ValueError):
            seal(self.source, self.source, self.token)
        seal(self.source, self.key, self.token)
        with self.assertRaises(ValueError):
            restore(self.token, self.key, self.key, overwrite=True)
