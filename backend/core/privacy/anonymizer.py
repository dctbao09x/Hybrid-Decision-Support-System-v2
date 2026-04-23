import re
from typing import Tuple
from backend.core.privacy.token_vault import token_vault


class PrivacyEngine:
	def __init__(self):
		# We simulate Presidio using some basic Vietnamese regex patterns
		self.patterns = {
			"EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
			"PHONE_NUMBER": r"0\d{9}",
			"PERSON": r"(Tôi tên là|Em là|Tên em là) ([A-Z][a-zà-ỹ]+(\s+[A-Z][a-zà-ỹ]+)+)",
			"SCHOOL": r"\b(Trường|THPT|THCS|ĐH|Đại học|University|College)\s+[A-ZÀ-Ỹ][\wÀ-ỹ\s\.]{2,}",
			"ADDRESS": r"\b\d{1,4}\s+[A-ZÀ-Ỹa-zà-ỹ0-9\s]{3,}(đường|phố|Street|St\.|P\.|Phường|Quận|District)\b",
		}
		self.injection_patterns = [
			r"ignore\s+previous",
			r"disregard\s+above",
			r"system\s+prompt",
			r"you\s+are\s+now",
			r"delete\s+all",
			r"bỏ\s+qua\s+các\s+lệnh",
			r"bỏ\s+qua\s+hướng\s+dẫn",
		]

	def anonymize(self, text: str) -> Tuple[str, str]:
		"""
		Detects PII, replaces it with tokens, and stores the mapping in TokenVault.
		Returns: vault_id, anonymized_text
		"""
		token_vault.cleanup_expired()
		vault_id = token_vault.start_session()
		anonymized_text = text

		# Process Regex patterns
		for entity_type, pattern in self.patterns.items():
			matches = list(re.finditer(pattern, anonymized_text))
			token_counter = 1

			# Process in reverse order to not mess up indices
			for match in reversed(matches):
				if entity_type == "PERSON":
					original_value = match.group(2)
					start = match.start(2)
					end = match.end(2)
				else:
					original_value = match.group(0)
					start = match.start()
					end = match.end()

				token = token_vault.create_token(entity_type, token_counter)
				token_counter += 1

				# Replace in text
				anonymized_text = anonymized_text[:start] + token + anonymized_text[end:]

				# Store
				token_vault.store_token(vault_id, token, original_value)

		return vault_id, anonymized_text

	def deanonymize(self, vault_id: str, text: str, clear: bool = True) -> str:
		"""
		Replaces tokens back with original PII from TokenVault.
		"""
		mapping = token_vault.get_mapping(vault_id)
		if not mapping:
			return text

		deanonymized_text = text
		for token, original_value in mapping.items():
			deanonymized_text = deanonymized_text.replace(token, original_value)

		if clear:
			token_vault.clear_session(vault_id)
		return deanonymized_text

	def finalize_session(self, vault_id: str) -> None:
		token_vault.clear_session(vault_id)

	def detect_prompt_injection(self, text: str) -> bool:
		lowered = text.lower()
		return any(re.search(pattern, lowered) for pattern in self.injection_patterns)


privacy_engine = PrivacyEngine()
