# backend/main.py
"""
Main entry point and test cases for Input Processing Layer
"""
import json
from backend.processor import process_user_profile

def test_basic_profile():
    """Test case 1: Basic profile with Vietnamese text"""
    print("=" * 80)
    print("TEST 1: Basic Profile")
    print("=" * 80)
    
    profile = {
        "personalInfo": {
            "fullName": "Nguyen Van A",
            "age": "18",
            "education": "THPT"
        },
        "interests": ["CNTT", "Thiết kế"],
        "skills": "Lập trình Python, tư duy logic",
        "careerGoal": "Muốn làm kỹ sư AI",
        "chatHistory": [
            {"role": "user", "text": "Em thích máy học"},
            {"role": "user", "text": "Muốn làm việc với dữ liệu"}
        ]
    }
    
    result = process_user_profile(profile)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()


def test_complex_profile():
    """Test case 2: Complex profile with multiple skills and interests"""
    print("=" * 80)
    print("TEST 2: Complex Profile")
    print("=" * 80)
    
    profile = {
        "personalInfo": {
            "fullName": "Tran Thi B",
            "age": "22",
            "education": "Đại học"
        },
        "interests": ["Kinh doanh", "Marketing", "Truyền thông"],
        "skills": "Quản lý dự án, giao tiếp tốt, tiếng Anh, photoshop, làm việc nhóm",
        "careerGoal": "Tôi muốn chuyển sang làm Product Manager và học thêm về công nghệ",
        "chatHistory": [
            {"role": "user", "text": "Tôi đang làm marketing nhưng muốn chuyển sang tech"},
            {"role": "user", "text": "Có nên học thêm lập trình không?"},
            {"role": "user", "text": "Tôi quan tâm đến AI và machine learning"}
        ]
    }
    
    result = process_user_profile(profile)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()


def test_minimal_profile():
    """Test case 3: Minimal profile with limited data"""
    print("=" * 80)
    print("TEST 3: Minimal Profile")
    print("=" * 80)
    
    profile = {
        "personalInfo": {
            "fullName": "Le Van C",
            "age": "20",
            "education": "Cao đẳng"
        },
        "interests": [],
        "skills": "",
        "careerGoal": "Chưa biết",
        "chatHistory": []
    }
    
    result = process_user_profile(profile)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()


def test_english_profile():
    """Test case 4: Profile with English text"""
    print("=" * 80)
    print("TEST 4: English Profile")
    print("=" * 80)
    
    profile = {
        "personalInfo": {
            "fullName": "Nguyen Van D",
            "age": "25",
            "education": "DaiHoc"
        },
        "interests": ["Technology", "Science", "Education"],
        "skills": "Python programming, data analysis, machine learning, problem solving",
        "careerGoal": "I want to become a Data Scientist and work with AI",
        "chatHistory": [
            {"role": "user", "text": "I am interested in artificial intelligence"},
            {"role": "user", "text": "Looking for a job in data science"}
        ]
    }
    
    result = process_user_profile(profile)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()


def test_special_characters():
    """Test case 5: Profile with special characters and messy text"""
    print("=" * 80)
    print("TEST 5: Special Characters and Messy Text")
    print("=" * 80)
    
    profile = {
        "personalInfo": {
            "fullName": "Phạm Thị E",
            "age": "19",
            "education": "Thạc sĩ"
        },
        "interests": ["Công nghệ thông tin!!!", "Thiết kế đồ họa???"],
        "skills": "   Lập trình C++, Java, Python... UI/UX design, @#$% Photoshop   ",
        "careerGoal": "Tôi muốn!!! học về AI và machine learning để trở thành engineer...",
        "chatHistory": [
            {"role": "user", "text": "Em muốn học về trí tuệ nhân tạo!!!"},
            {"role": "user", "text": "Có khóa training nào không???"}
        ]
    }
    
    result = process_user_profile(profile)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()


def test_all_intents():
    """Test case 6: Profile testing different intents"""
    print("=" * 80)
    print("TEST 6: Different Intents")
    print("=" * 80)
    
    profiles = [
        {
            "name": "Learning Intent",
            "data": {
                "personalInfo": {"fullName": "Test 1", "age": "20", "education": "THPT"},
                "interests": ["IT"],
                "skills": "Python",
                "careerGoal": "Muốn học thêm về AI và tham gia khóa đào tạo",
                "chatHistory": []
            }
        },
        {
            "name": "Career Intent",
            "data": {
                "personalInfo": {"fullName": "Test 2", "age": "23", "education": "DaiHoc"},
                "interests": ["Business"],
                "skills": "Management",
                "careerGoal": "Tìm việc làm ổn định và phát triển nghề nghiệp",
                "chatHistory": []
            }
        },
        {
            "name": "Switching Intent",
            "data": {
                "personalInfo": {"fullName": "Test 3", "age": "28", "education": "ThacSi"},
                "interests": ["IT"],
                "skills": "Marketing",
                "careerGoal": "Muốn chuyển ngành sang IT và đổi công việc mới",
                "chatHistory": []
            }
        }
    ]
    
    for profile_test in profiles:
        print(f"\n--- {profile_test['name']} ---")
        result = process_user_profile(profile_test['data'])
        print(f"Intent: {result['intent']}")
        print(f"Confidence: {result['confidence_score']}")
    
    print()


def main():
    """Run all test cases"""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "INPUT PROCESSING LAYER - DEMO" + " " * 29 + "║")
    print("╚" + "=" * 78 + "╝")
    print("\n")
    
    test_basic_profile()
    test_complex_profile()
    test_minimal_profile()
    test_english_profile()
    test_special_characters()
    test_all_intents()
    
    print("=" * 80)
    print("ALL TESTS COMPLETED")
    print("=" * 80)

if __name__ == "__main__":
    main()
