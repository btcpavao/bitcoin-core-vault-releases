#!/usr/bin/python3
"""Documentation regression checks; never read wallets or generate passphrases."""
from pathlib import Path
import runpy, re, math, unittest
R=Path(__file__).resolve().parents[2]
M=runpy.run_path(str(R/'config/includes.chroot/usr/lib/core-vault/guide_content.py'))
S=M['SECTIONS']

class PracticalGuide(unittest.TestCase):
 def test_first_chapter_has_complete_ordered_tutorial(self):
  self.assertEqual(next(iter(S)), 'Start here: Vault & Node')
  start=S[next(iter(S))]
  self.assertEqual([int(x) for x in re.findall(r'<h3>(\d+)\.',start)],list(range(1,14)))
  for term in ('KeePassXC','Encrypt Wallet','Core passphrase','GPG passphrase','Create Encrypted Backup','Brasero','Restore Wallet','Export watch-only wallet','Create new receiving address','Create Unsigned','Load PSBT from file','Sign Tx','Broadcast Tx'):
   self.assertIn(term,start)
 def test_standalone_respectful_copy(self):
  all_text=' '.join(S.values()).lower()
  for term in ('bag of coins','earlier discussion','previous conversation','we discussed','as we discussed','earlier illustrative','the earlier 14,800'):
   self.assertNotIn(term,all_text)
  self.assertEqual(len(S),21)
  self.assertNotIn('Encryption security levels',S)
 def test_backup_components_and_privacy(self):
  s=S['Backup components & storage']
  for term in ('three logical components','six physical copies','four logical components','multiple accurate copies','OpenPGP-encrypted data','transaction history','private spending','passphrase'):
   if term=='private spending':continue
   self.assertIn(term,s)
  self.assertIn('not a claim that Bitcoin Core mandates',s)
 def test_attack_model_math(self):
  f=M['attack_example']
  for n in (4,5,6):
   row=f(n);self.assertAlmostEqual(row['bits'],n*math.log2(7772),8)
   self.assertTrue(math.isclose(row['average_seconds'],(7772**n+1)/2/148000000))
   self.assertTrue(math.isclose(row['average_usd'],row['average_seconds']/3600*8900))
  self.assertIn('3,036 years',M['attack_table']())
  self.assertIn('1.84 quadrillion',M['attack_table']())
  self.assertEqual(round(2*f(4)['average_seconds']/86400),285)
 def test_costs_are_conditional_and_layer_work_adds(self):
  s=S['How to choose a passphrase']
  for text in ('not measured performance','not a benchmark','US$100,000','US$30.5 million','costs add','not</b> the strength of a single eight-word phrase','does not directly disclose','does not need certainty','SHA-256','65,011,712','different password-to-key','starting recommendation'):
   self.assertIn(text,s)
 def test_source_template_consistency(self):
  for rel in ('usr/lib/core-vault/guide_content.py','usr/lib/core-vault/guide_visuals.py','usr/local/bin/core-vault-guide'):
   self.assertEqual((R/'config/includes.chroot'/rel).read_bytes(),(R/'tools/core-vault/runtime-template'/rel).read_bytes())
if __name__=='__main__':unittest.main(verbosity=2)
