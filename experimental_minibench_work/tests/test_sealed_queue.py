import unittest
from sealed_queue import public_document, seal, unseal

T1="metaculus-test-token-"+("x"*45)
T2="metaculus-test-token-"+("y"*45)

class SealTests(unittest.TestCase):
    def test_roundtrip(self):
        payload={"p_yes":0.123,"reasoning":"private","question_id":9}
        blob=seal(payload,public_document(T1))
        self.assertEqual(unseal(blob,T1),payload)
        self.assertNotIn("private",str(blob))
        self.assertNotIn("0.123",str(blob))
    def test_different_keys_dont_decrypt(self):
        blob=seal({"p_yes":0.8},public_document(T1))
        with self.assertRaises(ValueError):unseal(blob,T2)
    def test_mutation_does_not_decrypt(self):
        blob=seal({"p_yes":0.8},public_document(T1))
        blob["ciphertext"]=blob["ciphertext"][:-4]+"AAAA"
        with self.assertRaises(Exception):unseal(blob,T1)
    def test_distinct_random_ciphertexts(self):
        doc=public_document(T1);p={"p_yes":0.8}
        self.assertNotEqual(seal(p,doc)["ciphertext"],seal(p,doc)["ciphertext"])
    def test_missing_token(self):
        with self.assertRaises(ValueError):public_document("")
if __name__=="__main__":unittest.main()
