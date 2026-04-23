from backend.taxonomy.facade import taxonomy


def test_skill_matching_vietnamese():
    skills = taxonomy.resolve_skills("Lập trình Python, tư duy logic")
    assert "Programming" in skills
    assert "Python" in skills
    assert "Logical Thinking" in skills


def test_education_mapping():
    edu = taxonomy.resolve_education("DaiHoc", return_id=False)
    assert edu == "Bachelor"


def test_intent_detection():
    intent = taxonomy.detect_intent("Muốn học thêm khóa học AI", return_id=True)
    assert intent == "learning_intent"
