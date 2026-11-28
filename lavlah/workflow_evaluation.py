"""Synthetic offline benchmark, not real-world accuracy evidence."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Case:
    question: str
    expected: str
    answer: str = ""

def fixtures():
    categories = ("Байршил", "Бараа", "Цаг", "Үнэ", "Хүргэлт")
    cases = []
    for category in categories:
        for i in range(1, 21):
            known = i <= 16
            cases.append(Case(f"Хиймэл төв {i}: {category}?", "answer" if known else "unavailable", f"Туршилтын {category} {i}" if known else ""))
    return tuple(cases)

def evaluate(cases, predict):
    total = correct = unsupported = errors = 0
    for case in cases:
        total += 1
        try:
            status, answer = predict(case.question)
            if status not in ("answer", "unavailable", "clarification") or not isinstance(answer, str):
                raise ValueError("invalid prediction")
            correct += int(status == case.expected and answer == case.answer)
            unsupported += int(bool(answer) and (case.expected != "answer" or answer != case.answer))
        except Exception:
            errors += 1
    return {"total": total, "correct": correct, "unsupported": unsupported, "errors": errors,
            "accuracy": correct / total if total else None}
