"""R1 — the real DAC registry of Presidency University.

Static, authoritative source for schools, departments, programmes, Deans, Heads of
Department, Member Secretaries of each DAC and the external member of each DAC.

Every entry below was read off *R1 — DAC List of School Name, Program Name, Member
Secretory and Chairperson* (supplied 1 Nov 2026), row by row, using the page images as
well as the text layer because the source is four Word tables pasted together. Nothing
here is invented: `source` on each entry records the group of the source document it came
from.

This module is a **constant**. Upgrades may extend it, but nothing may delete an entry:
the seeder only ever runs `INSERT OR IGNORE`, and the credentials sheet is generated
from this same list, so the people and their DACs survive every future version.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- helpers
def person(name, email, designation, *, school=None, department=None, **extra):
    record = {"name": name, "email": email.lower(), "designation": designation,
              "school": school, "department": department}
    record.update(extra)
    return record


def dac(department, code, programmes, hod, secretary, externals, *, note=""):
    return {"department": department, "code": code, "programmes": programmes,
            "hod": hod, "memberSecretary": secretary, "externalMembers": externals,
            "note": note}


# --------------------------------------------------------------------------- schools
R1_SCHOOLS = [
    {
        "name": "School of Engineering", "code": "SOE",
        "dean": person("Dr. Ramesh Sengottuvelu", "deansoe@presidencyuniversity.in",
                       "Professor & Dean, School of Engineering", school="School of Engineering"),
        "departments": [
            dac("Civil Engineering", "CIV",
                ["B.Tech in Civil Engineering",
                 "M. Tech. in Building and Construction Technology"],
                person("Dr. Nakul Ramanna", "hod_civ@presidencyuniversity.in",
                       "Head of the Department, Civil Engineering", department="Civil Engineering"),
                person("Mr. Ajay H A", "ajay@presidencyuniversity.in",
                       "Member Secretary (DAC), Civil Engineering", department="Civil Engineering"),
                [person("Dr. Chandrasekar Vadivelraju", "chandrasekar.v@presidencyuniversity.in",
                        "Professor, PSAIAC")]),
            dac("Electronics and Communication Engineering", "ECE",
                ["B.Tech in Electronics and Communication Engineering",
                 "B.Tech in VLSI", "B.Tech in VLSI Design Technology",
                 "M.Tech in Embedded System & VLSI"],
                person("Dr. Rajiv Ranjan Singh", "hod_ece@presidencyuniversity.in",
                       "Head of the Department, Electronics and Communication Engineering",
                       department="Electronics and Communication Engineering"),
                person("Dr. Sekar Ramalingam", "sekar.ramalingam@presidencyuniversity.in",
                       "Associate Professor, Dept. of ECE, SoE; Member Secretary (DAC), ECE",
                       department="Electronics and Communication Engineering"),
                [person("Dr. Swati Sharma", "swati.sharma@presidencyuniversity.in",
                        "Professor, SoCSE")]),
            dac("Electrical and Electronics Engineering", "EEE",
                ["B.Tech in Electrical and Electronics Engineering"],
                person("Dr. V Joshi Manohar", "hod_eee@presidencyuniversity.in",
                       "Head of the Department, Electrical and Electronics Engineering",
                       department="Electrical and Electronics Engineering"),
                person("Dr. MTL Gayatri", "gayatri.mtl@presidencyuniversity.in",
                       "Member Secretary (DAC), Electrical and Electronics Engineering",
                       department="Electrical and Electronics Engineering"),
                [person("Dr. Pradeep Kumar", "pradeepkumar@presidencyuniversity.in",
                        "Professor, Mathematics, SoE")]),
            dac("Mechanical Engineering", "MEC",
                ["B.Tech in Mechanical Engineering", "B.Tech Aerospace Engineering",
                 "M.Tech in Automotive Technology"],
                person("Dr. Satish Babu Boppana", "hod_mec@presidencyuniversity.in",
                       "Head of the Department, Mechanical Engineering",
                       department="Mechanical Engineering"),
                person("Dr. Aravinda T", "aravinda@presidencyuniversity.in",
                       "Assistant Professor-Selection Grade, Dept. of Mechanical Engg. SoE; "
                       "Member Secretary (DAC), MEC", department="Mechanical Engineering"),
                [person("Dr. C Komalavalli", "komalavalli.c@presidencyuniversity.in",
                        "Professor, SoIS")]),
            dac("Petroleum Engineering", "PET",
                ["B.Tech in Petroleum Engineering"],
                person("Dr. Suman Paul", "hod_pet@presidencyuniversity.in",
                       "Head of the Department, Petroleum Engineering",
                       department="Petroleum Engineering"),
                person("Dr. Niladri Shekhar Samanta", "niladri.shekhar@presidencyuniversity.in",
                       "Member Secretary (DAC), Petroleum Engineering",
                       department="Petroleum Engineering"),
                [person("Dr. K. Bhanu Rekha", "bhanurekha@presidencyuniversity.in",
                        "Associate Professor, Dept. of ECE, SoE")]),
            dac("Mathematics", "MAT",
                [],
                person("Dr. Shilpa N", "hod_maths@presidencyuniversity.in",
                       "Head of the Department, Mathematics", department="Mathematics"),
                person("Dr. C Muralidaran", "muralidaran.c@presidencyuniversity.in",
                       "Member Secretary (DAC), Mathematics", department="Mathematics"),
                [person("Dr. Vijayalakshmi P", "vijayalakshmi.p@presidencyuniversity.in",
                        "Professor, SoIS")],
                note="No programme is attached to this department in R1."),
            dac("Physics", "PHY",
                [],
                person("Dr. P Mohan Kumar Naidu", "hod_physics@presidencyuniversity.in",
                       "Head of the Department, Physics", department="Physics"),
                person("Dr. Bibi Raza Khanam", "bibi.raza@presidencyuniversity.in",
                       "Member Secretary (DAC), Physics", department="Physics"),
                [person("Dr. Anouja Mohanty", "anouja.mohanty@presidencyuniversity.in",
                        "Associate Professor, PSoC")],
                note="No programme is attached to this department in R1."),
            dac("Chemistry", "CHM",
                [],
                person("Dr. Saravanan Chandrasekaran", "hod_chemistry@presidencyuniversity.in",
                       "Head of the Department, Chemistry", department="Chemistry"),
                person("Dr. Pinki Pal", "pinki.pal@presidencyuniversity.in",
                       "Member Secretary (DAC), Chemistry", department="Chemistry"),
                [person("Dr. Sudha P", "sudha.p@presidencyuniversity.in",
                        "Associate Professor, SoCSE")],
                note="No programme is attached to this department in R1."),
        ],
        "schoolLevel": None,
    },
    {
        "name": "School of Computer Science and Engineering", "code": "SOCSE",
        "dean": person("Dr. Duraipandian N", "deancse@presidencyuniversity.in",
                       "Professor & Dean, School of Computer Science and Engineering",
                       school="School of Computer Science and Engineering"),
        "departments": [],
        "schoolLevel": {
            "department": None, "code": "CSE",
            "programmes": ["B.Tech in Computer Science and Engineering",
                           "B.Tech in Computer Science and Technology (CSG)",
                           "B.Tech in Computer Science and Information Technology (CSI)",
                           "B.Tech in Computer Science and Engineering (Networks) - CSN",
                           "B.Tech in Information Science and Technology (IST)",
                           "B.Tech in Information Science and Engineering (ISE)",
                           "B.Tech in Computer Engineering"],
            # R1 lists four HOD rows and three different member secretaries for this
            # school: one school-level DAC, with every R1 office holder offered.
            "hodCandidates": [
                person("Dr. Asif Mohammed H B", "asif.mohamed@presidencyuniversity.in",
                       "Head of the Department, School of Computer Science and Engineering",
                       school="School of Computer Science and Engineering"),
                person("Dr Nagaraj S R", "nagarajsr@presidencyuniversity.in",
                       "Head of the Department, School of Computer Science and Engineering",
                       school="School of Computer Science and Engineering"),
                person("Dr. Pallavi R", "pallavi.r@presidencyuniversity.in",
                       "Head of the Department, School of Computer Science and Engineering",
                       school="School of Computer Science and Engineering"),
                person("Dr. Gopalkrishna Shyam", "hod.cse4@presidencyuniversity.in",
                       "Head of the Department, School of Computer Science and Engineering",
                       school="School of Computer Science and Engineering"),
            ],
            "secretaryCandidates": [
                person("Ms. Shaik Salma Begum", "shaiksalma@presidencyuniversity.in",
                       "Member Secretary (DAC), School of Computer Science and Engineering",
                       school="School of Computer Science and Engineering"),
                person("Dr. Praveena KN", "praveenakn@presidencyuniversity.in",
                       "Member Secretary (DAC), School of Computer Science and Engineering",
                       school="School of Computer Science and Engineering"),
                person("Dr. Amirtha Preeya Venkatachalam", "amirthapreeya@presidencyuniversity.in",
                       "Member Secretary (DAC), School of Computer Science and Engineering",
                       school="School of Computer Science and Engineering"),
            ],
            "externalMembers": [
                person("Dr. T. Aravinda", "aravinda@presidencyuniversity.in",
                        "Assistant Professor-Selection Grade, Dept. of Mechanical Engg. SoE"),
                person("Dr. Vanithalakshmi Mariappan", "vanithalakshmi.m@presidencyuniversity.in",
                        "Associate Professor, Dept. of ECE, SOE"),
                person("Mr.Gopalakrishnan N", "gopalakrishnan@presidencyuniversity.in",
                        "Assistant Professor, Dept. of Civil Engg. SoE"),
            ],
            "note": "R1 gives no department for this school; it is one school-level DAC.",
        },
    },
    {
        "name": "School of Artificial Intelligence and Advanced Computing", "code": "SOAIAC",
        "dean": person("Dr. Shakkeera L", "shakkeera.l@presidencyuniversity.in",
                       "Professor & Dean, School of Artificial Intelligence and Advanced Computing",
                       school="School of Artificial Intelligence and Advanced Computing"),
        "departments": [
            dac("Data Science and Computing System", "DSC",
                ["B.Tech in Artificial Intelligence and Data Science",
                 "B.Tech in Computer Science and Technology Big Data (CBD)",
                 "B.Tech in Computer Science and Engineering (Data Science)",
                 "B.Tech in Computer Science and Engineering",
                 "Post Graduate Diploma (PBD) In Big Data"],
                person("Dr. Pravinth Raja", "hod.dsc_psaiac@presidencyuniversity.in",
                       "Head of the Department, Data Science and Computing System",
                       department="Data Science and Computing System"),
                person("Ms. Thabassum Khan", "thabassumkhan@presidencyuniversity.in",
                       "Member Secretary (DAC), Data Science and Computing System",
                       department="Data Science and Computing System"),
                [person("Dr. Muthupandi Gandhi", "muthupandi@presidencyuniversity.in",
                        "Associate Professor - Selection Grade, Dept. of ECE, SoE")]),
            dac("Artificial Intelligence and Robotics", "AIR",
                ["Master of Technology (M.Tech.) in Computer Science and Engineering",
                 "Diploma in Artificial Intelligence (PAI)",
                 "B.Tech in Computer Science and Engineering (Artificial Intelligence and "
                 "Machine Learning)",
                 "B.Tech in Robotics and Artificial Intelligence (RAI)"],
                person("Dr. Zafar Ali Khan", "zafaralikhan@presidencyuniversity.in",
                       "Head of the Department, Artificial Intelligence and Robotics",
                       department="Artificial Intelligence and Robotics"),
                person("Dr. Poonam Nilesh Yadav", "poonam.nilesh@presidencyuniversity.in",
                       "Member Secretary (DAC), Artificial Intelligence and Robotics",
                       department="Artificial Intelligence and Robotics"),
                [person("Dr. Sekar R", "sekar.ramalingam@presidencyuniversity.in",
                        "Associate Professor, Dept. of ECE, SoE")]),
            dac("Cyber Security and Intelligence System", "CSI",
                ["B.Tech in Computer Science and Engineering Block Chain (CBC)",
                 "Post Graduate Bachelor of Technology (B.Tech.) in Computer Science and "
                 "Engineering-Cyber Security (CCS)",
                 "B.Tech in Computer Science and Technology Devops (CDV)",
                 "B.Tech in Computer Science and Engineering- Internet Of Things(CIT)"],
                person("Dr. Sampath A K", "sampath.ak@presidencyuniversity.in",
                       "Head of the Department, Cyber Security and Intelligence System",
                       department="Cyber Security and Intelligence System"),
                person("Ms Swetha Rajagopal", "swetha.rajagopal@presidencyuniversity.in",
                       "Member Secretary (DAC), Cyber Security and Intelligence System",
                       department="Cyber Security and Intelligence System"),
                [person("Dr. Ramachandra C G", "ramachandracg@presidencyuniversity.in",
                        "Professor, Dept. of Mechanical Engg. SoE")]),
        ],
        "schoolLevel": None,
    },
    {
        "name": "School of Information Science", "code": "SOIS",
        "dean": person("Dr. Mahalakshmi R", "mahalakshmi@presidencyuniversity.in",
                       "Professor & Dean, School of Information Science",
                       school="School of Information Science"),
        "departments": [],
        "schoolLevel": {
            "department": None, "code": "ISC",
            "programmes": ["Master in Computer Application", "Master in Data Science",
                           "Bachelor of Computer Application",
                           "Bachelor of Computer Application (Artificial Intelligence and "
                           "Machine Learning)",
                           "Bachelor of Computer Application (Data Science)",
                           "BSc in Computer Science",
                           "BSc in AI, Data Science and Cloud Computing"],
            "hodCandidates": [
                person("Dr.Renuka Devi M.", "renukadevi.m@presidencyuniversity.in",
                       "Head of the Department, School of Information Science",
                       school="School of Information Science"),
                person("Dr.Vetrimani Elangovan", "vetrimani.elangovan@presidencyuniversity.in",
                       "Head of the Department, School of Information Science",
                       school="School of Information Science"),
            ],
            "secretaryCandidates": [
                person("Dr. Vijayalakshmi", "vijayalakshmi.p@presidencyuniversity.in",
                       "Professor, SoIS; Member Secretary (DAC), School of Information Science",
                       school="School of Information Science"),
                person("Dr. Salma Firdose", "salma.firdose@presidencyuniversity.in",
                       "Member Secretary (DAC), School of Information Science",
                       school="School of Information Science"),
            ],
            "externalMembers": [
                person("Dr. Jayavadivel Ravi", "jayavadivel.ravi@presidencyuniversity.in",
                        "Associate Professor - Selection Grade"),
                person("Dr. Vignesh R", "vigneshr@presidencyuniversity.in",
                        "Associate Professor - Selection Grade, PSAIAC"),
            ],
            "note": "R1 gives no department for this school; it is one school-level DAC.",
        },
    },
    {
        "name": "School of Design", "code": "SOD",
        "dean": person("Ms. Srishti Bajaj", "director_sod@presidencyuniversity.in",
                       "Director, School of Design", school="School of Design"),
        "departments": [],
        "schoolLevel": {
            "department": None, "code": "DES",
            "programmes": ["Bachelors of Design", "BSc Multimedia", "Bachelor of Fine Arts"],
            "hodCandidates": [
                person("Mr. Abhilash. B. S", "abhilash.b.s@presidencyuniversity.in",
                       "Head of the Department, School of Design", school="School of Design"),
            ],
            "secretaryCandidates": [
                person("Dr. Bhagyashree Nadig Y S", "bhagyashree.nadig@presidencyuniversity.in",
                       "Member Secretary (DAC), School of Design", school="School of Design"),
            ],
            "externalMembers": [
                person("Dr. Syed Abid Hussain", "syedabid.hussain@presidencyuniversity.in",
                        "Professor, SoC"),
            ],
            "note": "",
        },
    },
    {
        "name": "School of Management", "code": "SOM",
        "dean": person("Dr. Sagi Srilalitha Girija Kumari", "deansom@presidencyuniversity.in",
                       "Professor & Dean, School of Management", school="School of Management"),
        "departments": [],
        "schoolLevel": {
            "department": None, "code": "MGT",
            "programmes": ["Master in Business Administration", "MBA Marketing and Finance",
                           "MBA Banking and Finance", "MBA Business Analytics",
                           "MBA Digital Marketing"],
            "hodCandidates": [],
            "secretaryCandidates": [
                person("Dr. Megha Pandey", "megha.pandey@presidencyuniversity.in",
                       "Member Secretary (DAC), School of Management", school="School of Management"),
            ],
            "externalMembers": [
                person("Dr. Safinaz S.", "safinazs@presidencyuniversity.in",
                        "Associate Professor, Dept. of ECE, PSOE"),
            ],
            "note": "R1 prints NA for the Head of the Department of this school.",
        },
    },
    {
        "name": "School of Management – BBA programs", "code": "SOMBBA",
        "dean": person("Dr. Padmavathi", "deansoc@presidencyuniversity.in",
                       "Professor & Dean, School of Commerce", school="School of Commerce"),
        "departments": [],
        "schoolLevel": {
            "department": None, "code": "BBA",
            "programmes": ["BBA Aviation Management", "Bachelor in Business Administration",
                           "Bachelor in Business Analytics", "Bachelor in Digital Marketing",
                           "Bachelor in (Digital Business)", "Bachelor in Commerce",
                           "Bachelor in Commerce (CMA)",
                           "Bachelor in Commerce (Business Analytics)",
                           "Bachelor in Commerce (ACCA)",
                           "Bachelor in Commerce (CA Foundation)"],
            "hodCandidates": [
                person("Dr. Saba Inamdar", "hod_soc@presidencyuniversity.in",
                       "Head of the Department, School of Management – BBA programs",
                       school="School of Management – BBA programs"),
            ],
            "secretaryCandidates": [
                person("Dr. Shabeena", "shabeena@presidencyuniversity.in",
                       "Member Secretary (DAC), School of Management – BBA programs",
                       school="School of Management – BBA programs"),
            ],
            "externalMembers": [
                # R1 prints akhila.udupa@ here, which is Dr. Akhila R Udupa's address (the
                # Commerce external member). Two people cannot share one login mailbox, so
                # Dr. Nandini Sinha keeps her R1 name and designation with a derived address.
                person("Dr. Nandini Sinha", "nandini.sinha@presidencyuniversity.in",
                        "Associate Professor, SoM"),
            ],
            "note": "",
        },
    },
    {
        "name": "School of Commerce", "code": "SOC",
        "dean": person("Dr. Padmavathi", "deansoc@presidencyuniversity.in",
                       "Professor & Dean, School of Commerce", school="School of Commerce"),
        "departments": [],
        "schoolLevel": {
            "department": None, "code": "COM",
            "programmes": ["Bachelor in Commerce (Business Analytics)",
                           "Bachelor in Commerce (ACCA)", "Bachelor in Commerce (CA Foundation)"],
            "hodCandidates": [
                person("Dr. Poornima Karthikeyan", "poornima.karthikeyan@presidencyuniversity.in",
                       "Head of the Department, School of Commerce", school="School of Commerce"),
            ],
            "secretaryCandidates": [
                person("Dr. Mohammed Nabeel K", "nabeel@presidencyuniversity.in",
                       "Member Secretary (DAC), School of Commerce", school="School of Commerce"),
            ],
            "externalMembers": [
                person("Dr. Akhila R Udupa", "akhila.udupa@presidencyuniversity.in",
                        "Professor, SoM"),
            ],
            "note": "",
        },
    },
    {
        "name": "School of Law", "code": "SOL",
        "dean": person("Dr. Saroj Sharma", "deansol@presidencyuniversity.in",
                       "Professor & Dean, School of Law", school="School of Law"),
        "departments": [],
        "schoolLevel": {
            "department": None, "code": "LAW",
            "programmes": ["Bachelor of Arts LLB", "Bachelor of Business Administration LLB",
                           "Bachelor of Commerce LLB", "LLM"],
            "hodCandidates": [
                person("Dr. G M Mamatha", "mamatha.gm@presidencyuniversity.in",
                       "Head of the Department, School of Law", school="School of Law"),
            ],
            "secretaryCandidates": [
                person("Dr. Rima Gosh", "rima@presidencyuniversity.in",
                       "Member Secretary (DAC), School of Law", school="School of Law"),
            ],
            "externalMembers": [
                person("Dr. Prachi Beriwala", "prachi.beriwala@presidencyuniversity.in",
                        "Associate Professor, SoC"),
            ],
            "note": "",
        },
    },
    {
        "name": "School of Media Studies", "code": "SOMS",
        "dean": None,
        "departments": [],
        "schoolLevel": {
            "department": None, "code": "MED",
            "programmes": ["Bachelors in Journalism", "Masters in Journalism"],
            "hodCandidates": [
                person("Dr. Ashish Sharma", "ashish.sharma@presidencyuniversity.in",
                       "Head of the Department, School of Media Studies",
                       school="School of Media Studies"),
            ],
            "secretaryCandidates": [
                person("Dr. Garima Ganghariya", "garima.g@presidencyuniversity.in",
                       "Member Secretary (DAC), School of Media Studies",
                       school="School of Media Studies"),
            ],
            "externalMembers": [
                person("Mr. Madhusudana M.", "madhusudhan@presidencyuniversity.in",
                        "Assistant Professor, SoD"),
            ],
            "note": "R1 prints NA for the Dean of this school.",
        },
    },
    {
        "name": "School of Liberal Arts and Sciences", "code": "SOLAS",
        "dean": None,
        "departments": [],
        "schoolLevel": {
            "department": None, "code": "LAS",
            "programmes": ["MSc Psychology", "Master of Arts", "BSc Psychology",
                           "MA in English"],
            "hodCandidates": [
                person("Dr. Pritha Sanyal", "pritha.sanyal@presidencyuniversity.in",
                       "Head of the Department, School of Liberal Arts and Sciences",
                       school="School of Liberal Arts and Sciences"),
            ],
            "secretaryCandidates": [
                person("Dr. Tcchicus David", "tychicus@presidencyuniversity.in",
                       "Member Secretary (DAC), School of Liberal Arts and Sciences",
                       school="School of Liberal Arts and Sciences"),
            ],
            "externalMembers": [
                person("Dr.Divya Nair", "divya.nair@presidencyuniversity.in",
                        "Assistant Professor, Dept. of Civil Engg. SoE"),
            ],
            "note": "R1 prints NA for the Dean of this school.",
        },
    },
    {
        "name": "School of Allied Health Care Professions", "code": "SOAHC",
        "dean": None,
        "departments": [],
        "schoolLevel": {
            "department": None, "code": "AHC",
            "programmes": ["Bachelor of Physiotherapy", "Bachelor of Occupation Therapy",
                           "School of Allied Health Science"],
            "hodCandidates": [
                person("Dr. Purnima Singh", "purnimasingh@presidencyuniversity.in",
                       "Head of the Department, School of Allied Health Care Professions",
                       school="School of Allied Health Care Professions"),
            ],
            "secretaryCandidates": [
                person("Dr. Richa Ravindra Singh", "richa@presidencyuniversity.in",
                       "Member Secretary (DAC), Bachelor of Physiotherapy",
                       school="School of Allied Health Care Professions"),
                person("Dr. Unnishri", "unnisri@presidencyuniversity.in",
                       "Member Secretary (DAC), Bachelor of Occupation Therapy",
                       school="School of Allied Health Care Professions"),
                person("Ms Apoorva Shetty", "apoorvashetty@presidencyuniversity.in",
                       "Member Secretary (DAC), School of Allied Health Science",
                       school="School of Allied Health Care Professions"),
            ],
            "externalMembers": [
                person("Dr. Veena C.S", "veena.cs@presidencyuniversity.in",
                        "Professor, Dept. of ECE, SoE"),
                person("Dr. Murali Parameswaran", "murali.p@presidencyuniversity.in",
                        "Professor, PSoCSE"),
                person("Dr. N. Srikanth Reddy", "srikanthreddyn@presidencyuniversity.in",
                        "Assistant Professor, SoM"),
            ],
            "note": "R1 leaves the Dean as NA; three programme Member Secretaries added in R1 order (Nov 2026).",
        },
    },
]


# --------------------------------------------------------------------------- derived
def school_names() -> list[str]:
    return [school["name"] for school in R1_SCHOOLS]


def departments_of(school_name: str) -> list[str]:
    for school in R1_SCHOOLS:
        if school["name"] == school_name:
            return [department["department"] for department in school["departments"]]
    return []


def dacs() -> list[dict]:
    """Every DAC in R1: one per department, or one per school that has no department."""
    out = []
    for school in R1_SCHOOLS:
        if school["departments"]:
            for department in school["departments"]:
                out.append({"school": school["name"], "dean": school["dean"], **department})
        elif school["schoolLevel"]:
            level = school["schoolLevel"]
            out.append({"school": school["name"], "dean": school["dean"],
                        "department": level["department"], "code": level["code"],
                        "programmes": level["programmes"],
                        "hodCandidates": level["hodCandidates"],
                        "secretaryCandidates": level["secretaryCandidates"],
                        "externalMembers": level["externalMembers"],
                        "note": level.get("note", "")})
    return out


def all_people() -> dict[str, dict]:
    """Every person in R1, keyed by email, with the roles they hold."""
    people: dict[str, dict] = {}

    def add(record, role, school, department):
        email = str(record["email"]).lower()
        row = people.setdefault(email, {"name": record["name"], "email": email,
                                        "designation": record.get("designation", ""),
                                        "school": record.get("school") or school,
                                        "department": record.get("department") or department,
                                        "roles": []})
        entry = f"{role}:{department or school}"
        if entry not in row["roles"]:
            row["roles"].append(entry)

    for school in R1_SCHOOLS:
        if school["dean"]:
            add(school["dean"], "Dean", school["name"], None)
        for department in school["departments"]:
            add(department["hod"], "HOD", school["name"], department["department"])
            add(department["memberSecretary"], "MemberSecretary", school["name"],
                department["department"])
            for external in department["externalMembers"]:
                add(external, "ExternalMember", school["name"], department["department"])
        level = school["schoolLevel"]
        if level:
            for hod in level["hodCandidates"]:
                add(hod, "HOD", school["name"], None)
            for secretary in level["secretaryCandidates"]:
                add(secretary, "MemberSecretary", school["name"], None)
            for external in level["externalMembers"]:
                add(external, "ExternalMember", school["name"], None)
    return people


if __name__ == "__main__":
    everyone = all_people()
    print(f"schools: {len(R1_SCHOOLS)} · DACs: {len(dacs())} · people: {len(everyone)}")
    for school in R1_SCHOOLS:
        print(f"\n{school['name']}")
        dean = school["dean"]
        print(f"  Dean: {dean['name'] + ' <' + dean['email'] + '>' if dean else '— (NA in R1)'}")
        if school["departments"]:
            for department in school["departments"]:
                print(f"  · {department['department']}")
                print(f"      HOD : {department['hod']['name']} <{department['hod']['email']}>")
                print(f"      MS  : {department['memberSecretary']['name']} "
                      f"<{department['memberSecretary']['email']}>")
                for external in department["externalMembers"]:
                    print(f"      EXT : {external['name']} — {external['designation']} "
                          f"<{external['email']}>")
                print(f"      PRG : {len(department['programmes'])}")
        else:
            level = school["schoolLevel"]
            print(f"  · school-level DAC ({level['code']})")
            print("      HOD : " + (", ".join(p["name"] for p in level["hodCandidates"]) or "—"))
            print("      MS  : " + (", ".join(p["name"] for p in level["secretaryCandidates"]) or "—"))
            for external in level["externalMembers"]:
                print(f"      EXT : {external['name']} — {external['designation']} <{external['email']}>")
            print(f"      PRG : {len(level['programmes'])}")
