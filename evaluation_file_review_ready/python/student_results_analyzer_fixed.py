"""
Student Results Analyzer - fixed reference version.

Business rules:
- Only marks from 0 to 100 inclusive are valid.
- Invalid student records must be ignored.
- A mark of 40 or above is a pass.
- Grade boundaries: A >= 70, B >= 60, C >= 50, D >= 40, otherwise F.
- Highest-scoring student must be returned.
- Pass percentage must be from 0 to 100.
"""

def valid_students(students):
    valid = []
    for student in students:
        name = str(student.get("name", "")).strip()
        mark = student.get("mark")
        if not name:
            continue
        if not isinstance(mark, (int, float)):
            continue
        if mark < 0 or mark > 100:
            continue
        valid.append({"name": name, "mark": float(mark)})
    return valid


def calculate_average(students):
    students = valid_students(students)
    if not students:
        return 0.0
    return sum(student["mark"] for student in students) / len(students)


def has_passed(mark):
    return mark >= 40


def assign_grade(mark):
    if mark >= 70:
        return "A"
    if mark >= 60:
        return "B"
    if mark >= 50:
        return "C"
    if mark >= 40:
        return "D"
    return "F"


def find_highest_student(students):
    students = valid_students(students)
    if not students:
        return None
    return max(students, key=lambda student: student["mark"])


def calculate_pass_percentage(students):
    students = valid_students(students)
    if not students:
        return 0.0

    passed = sum(1 for student in students if has_passed(student["mark"]))
    return (passed / len(students)) * 100


def build_report(students):
    valid = valid_students(students)
    return {
        "valid_count": len(valid),
        "average": round(calculate_average(valid), 2),
        "highest_student": find_highest_student(valid),
        "pass_percentage": round(calculate_pass_percentage(valid), 2),
        "grades": {
            student["name"]: assign_grade(student["mark"])
            for student in valid
        },
    }


if __name__ == "__main__":
    sample = [
        {"name": "Asha", "mark": 82},
        {"name": "Ben", "mark": 70},
        {"name": "Cara", "mark": 40},
        {"name": "Dev", "mark": 35},
        {"name": "", "mark": 88},
        {"name": "Eva", "mark": 110},
    ]
    
    report = build_report(sample)

print("\n--- Student Results Report ---")
print(f"Valid students: {report['valid_count']}")
print(f"Average mark: {report['average']}")
print(
    f"Highest-scoring student: "
    f"{report['highest_student']['name']} "
    f"({report['highest_student']['mark']})"
)
print(f"Pass percentage: {report['pass_percentage']}%")

print("Grades:")
for name, grade in report["grades"].items():
    print(f"  {name}: {grade}")
