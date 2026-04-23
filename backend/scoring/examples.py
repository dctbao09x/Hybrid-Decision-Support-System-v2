# Example usage: Using SIMGRScorer as the unified entry point
# backend/scoring/examples.py

import json
from backend.scoring import SIMGRScorer


def example_1_basic_scoring():
    """Example 1: Basic scoring with default config and weighted strategy."""
    scorer = SIMGRScorer(strategy="weighted")

    input_data = {
        "user": {
            "skills": ["python", "machine learning"],
            "interests": ["AI", "data science"],
        },
        "careers": [
            {
                "name": "Data Scientist",
                "required_skills": ["python"],
                "ai_relevance": 0.95,
            },
            {
                "name": "Backend Engineer",
                "required_skills": ["java"],
                "ai_relevance": 0.3,
            },
        ]
    }

    output = scorer.score(input_data)
    print(json.dumps(output, indent=2))


def example_2_custom_strategy():
    """Example 2: Using personalized strategy."""
    scorer = SIMGRScorer(strategy="personalized")

    input_data = {
        "user": {
            "skills": ["python"],
            "interests": ["AI"],
            "ability_score": 0.8,
            "confidence_score": 0.6,
        },
        "careers": [
            {
                "name": "ML Engineer",
                "required_skills": ["python"],
                "ai_relevance": 1.0,
                "growth_rate": 0.9,
            }
        ]
    }

    output = scorer.score(input_data)
    print(json.dumps(output, indent=2))


def example_3_custom_weights():
    """Example 3: Override weights in input."""
    scorer = SIMGRScorer()

    input_data = {
        "user": {
            "skills": ["python"],
            "interests": ["data"],
        },
        "careers": [
            {
                "name": "Data Scientist",
                "required_skills": ["python"],
                "ai_relevance": 0.8,
                "growth_rate": 0.7,
            }
        ],
        "config": {
            "study_score": 0.4,      # Increased from 0.25
            "interest_score": 0.2,   # Decreased
            "market_score": 0.2,     # Decreased
            "growth_score": 0.15,    # Same
            "risk_score": 0.05,      # Decreased
        }
    }

    output = scorer.score(input_data)
    print("Custom config output:")
    print(f"Config used: {output['config_used']}")
    print(f"Best match: {output['ranked_careers'][0]['name']} "
          f"({output['ranked_careers'][0]['total_score']})")


def example_4_error_handling():
    """Example 4: Error handling."""
    scorer = SIMGRScorer(debug=False)  # debug=False suppresses exceptions

    # Invalid input
    bad_input = {
        "user": "not a dict",  # Invalid
        "careers": []
    }

    output = scorer.score(bad_input)
    print(f"Success: {output['success']}")
    print(f"Error: {output['error']}")


def example_5_complete_profile():
    """Example 5: Complete user profile with all fields."""
    scorer = SIMGRScorer(strategy="personalized")

    input_data = {
        "user": {
            "skills": ["python", "java", "sql", "machine learning"],
            "interests": ["AI", "data science", "backend systems"],
            "education_level": "Master",
            "ability_score": 0.85,
            "confidence_score": 0.8,
        },
        "careers": [
            {
                "name": "Data Scientist",
                "required_skills": ["python", "machine learning"],
                "preferred_skills": ["sql", "statistics"],
                "domain": "AI",
                "ai_relevance": 0.95,
                "growth_rate": 0.85,
                "competition": 0.7,
            },
            {
                "name": "AI Engineer",
                "required_skills": ["python", "machine learning"],
                "preferred_skills": ["java", "deployment"],
                "domain": "AI",
                "ai_relevance": 0.9,
                "growth_rate": 0.9,
                "competition": 0.8,
            },
            {
                "name": "Backend Engineer",
                "required_skills": ["java", "sql"],
                "preferred_skills": ["system design"],
                "domain": "Backend",
                "ai_relevance": 0.2,
                "growth_rate": 0.5,
                "competition": 0.6,
            },
        ]
    }

    output = scorer.score(input_data)

    print("===== COMPLETE SCORING RESULT =====")
    print(f"Success: {output['success']}")
    print(f"Evaluated: {output['total_evaluated']} careers\n")
    print(f"SIMGR Weights Used:")
    for component, weight in output['config_used'].items():
        print(f"  {component}: {weight}")
    print()

    for career in output['ranked_careers']:
        print(f"#{career['rank']} {career['name'].upper()}")
        print(f"  Total Score: {career['total_score']}")
        bd = career['breakdown']
        print(f"  Study:    {bd['study_score']:.2f} (skill match)")
        print(f"  Interest: {bd['interest_score']:.2f} (domain alignment)")
        print(f"  Market:   {bd['market_score']:.2f} (attractiveness)")
        print(f"  Growth:   {bd['growth_score']:.2f} (potential)")
        print(f"  Risk:     {bd['risk_score']:.2f} (low=0, high=1)")
        print()


if __name__ == "__main__":
    print("\n========== EXAMPLE 1: BASIC SCORING ==========\n")
    example_1_basic_scoring()

    print("\n========== EXAMPLE 2: PERSONALIZED STRATEGY ==========\n")
    example_2_custom_strategy()

    print("\n========== EXAMPLE 3: CUSTOM WEIGHTS ==========\n")
    example_3_custom_weights()

    print("\n========== EXAMPLE 4: ERROR HANDLING ==========\n")
    example_4_error_handling()

    print("\n========== EXAMPLE 5: COMPLETE PROFILE ==========\n")
    example_5_complete_profile()
