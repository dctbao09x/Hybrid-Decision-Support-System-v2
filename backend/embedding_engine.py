# backend/embedding_engine.py
"""
Embedding & Similarity Layer for Career Guidance System
Uses sentence-transformers for semantic matching between user profiles and careers
"""

import re
import numpy as np
from typing import List, Dict, Tuple
from sentence_transformers import SentenceTransformer
try:
    import faiss
    _FAISS_AVAILABLE = True
except ImportError:
    faiss = None  # type: ignore[assignment]
    _FAISS_AVAILABLE = False


# ==================== CAREER CORPUS ====================
# Covers all careers registered in the Knowledge Base (career_kb.db).
# Kept in sync with backend/rule_engine/prototype_jobs.py JOB_DATABASE.
CAREER_CORPUS = {
    # ── AI / DATA ─────────────────────────────────────────────────────────
    "AI Engineer": """
        Artificial Intelligence Engineer Machine Learning Deep Learning
        Neural Networks TensorFlow PyTorch Python Data Science
        Computer Vision NLP Algorithm Research Development
        Trí tuệ nhân tạo Kỹ sư AI Học máy Mạng nơ-ron
    """,
    "Machine Learning Engineer": """
        Machine Learning MLOps Model Deployment Production
        Python TensorFlow PyTorch Scikit-learn Feature Engineering
        Model Optimization Cloud AWS Azure Algorithm
        Kỹ sư máy học Triển khai mô hình
    """,
    "AI Researcher": """
        AI Research Deep Learning Publications Neural Architecture
        Math Statistics Paper Writing Theory Experimentation
        NLP Computer Vision Reinforcement Learning PhD Research
        Nghiên cứu AI Nghiên cứu học sâu
    """,
    "Data Scientist": """
        Data Science Analytics Statistics Machine Learning Python R
        SQL Database Big Data Visualization Pandas NumPy
        Business Intelligence Predictive Modeling Data Mining
        Khoa học dữ liệu Phân tích dữ liệu Thống kê
    """,
    "Data Analyst": """
        Data Analysis Business Analytics SQL Excel Tableau
        Dashboard Reporting Visualization Metrics KPI
        Business Intelligence Statistics Python R
        Phân tích dữ liệu Báo cáo Trực quan hóa
    """,
    "Data Engineer": """
        Data Engineering ETL Pipeline Apache Spark Hadoop Kafka
        SQL Python Big Data Cloud Warehouse Databricks Airflow
        Data Infrastructure Data Lake Streaming
        Kỹ sư dữ liệu Xây dựng pipeline dữ liệu
    """,
    "BI Developer": """
        Business Intelligence Power BI Tableau Qlik DAX MDX
        Data Modeling SQL Dashboard Reporting ETL Datawarehouse
        KPI Analytics Visualization Excel
        Phát triển BI Báo cáo kinh doanh
    """,
    "Growth Analyst": """
        Growth Hacking Analytics A/B Testing Funnel Retention
        SQL Python Marketing Analytics Product Analytics
        User Acquisition Experimentation Metrics Dashboard
        Phân tích tăng trưởng Marketing dữ liệu
    """,
    "Machine OPS Engineer": """
        MLOps Machine Learning Operations Model Deployment Monitoring
        Docker Kubernetes MLflow Kubeflow CI/CD Cloud
        Model Registry Feature Store Experiment Tracking
        Kỹ sư vận hành ML Triển khai mô hình AI
    """,
    "ML Ops Engineer": """
        MLOps Machine Learning Operations Model Deployment Monitoring
        Docker Kubernetes MLflow Kubeflow CI/CD Cloud
        Model Registry Feature Store Experiment Tracking
        Kỹ sư MLOps Vận hành mô hình máy học
    """,

    # ── SOFTWARE ──────────────────────────────────────────────────────────
    "Software Engineer": """
        Software Engineering Programming Algorithms Data Structures
        OOP Design Patterns Git Code Review Testing
        Java Python C++ Go Backend Frontend System Design
        Kỹ sư phần mềm Lập trình viên
    """,
    "Backend Developer": """
        Backend Development API REST GraphQL Database SQL NoSQL
        Node.js Python Java Spring Boot Django Flask
        Microservices Cloud Server Architecture
        Phát triển backend Lập trình server
    """,
    "Frontend Developer": """
        Frontend Development React Vue Angular JavaScript TypeScript
        HTML CSS Responsive Design Web Development UI
        Redux State Management REST API GraphQL
        Phát triển giao diện Lập trình web Giao diện người dùng
    """,
    "Full Stack Developer": """
        Full Stack Web Development Frontend Backend JavaScript
        React Node.js PostgreSQL REST API Docker Deployment
        TypeScript HTML CSS Authentication Cloud
        Lập trình viên full stack Phát triển web toàn diện
    """,
    "Mobile Developer": """
        Mobile App Development Flutter React Native iOS Android
        Kotlin Swift Dart API Integration UI Mobile Design
        App Store Google Play Push Notifications
        Lập trình viên mobile Phát triển ứng dụng di động
    """,
    "Game Developer": """
        Game Development Unity Unreal C# C++ Game Design
        3D Graphics Physics Engine Animation Game Logic
        Scripting Level Design Multiplayer Gaming
        Lập trình game Phát triển trò chơi
    """,
    "Blockchain Developer": """
        Blockchain Solidity Smart Contracts Ethereum Web3 DeFi
        NFT Cryptocurrency Decentralized Applications Hardhat
        Truffle Metamask Token Protocol Security Audit
        Lập trình blockchain Hợp đồng thông minh
    """,
    "Database Administrator": """
        Database Administration SQL PostgreSQL MySQL NoSQL MongoDB
        Performance Tuning Indexing Backup Recovery Replication
        Oracle DBA High Availability Security Schema Design
        Quản trị cơ sở dữ liệu DBA
    """,
    "QA Engineer": """
        Quality Assurance Testing Automation Selenium Test Cases
        Manual Testing Bug Tracking JIRA Regression Testing
        Performance Testing API Testing CI/CD Quality Control
        Kiểm thử phần mềm Đảm bảo chất lượng
    """,
    "Technical Writer": """
        Technical Documentation API Documentation User Guide
        Markdown Writing Research Developer Docs SDK Docs
        Clarity Communication Technical Communication Editing
        Viết tài liệu kỹ thuật Tài liệu phần mềm
    """,
    "Freelance Developer": """
        Freelance Programming Client Projects Web Mobile App
        Self-employed Remote Work Portfolio Upwork Fiverr
        Multi-stack Contract Development Business
        Lập trình viên tự do Freelance
    """,

    # ── CLOUD / DEVOPS / INFRA ────────────────────────────────────────────
    "DevOps Engineer": """
        DevOps CI/CD Jenkins Docker Kubernetes Infrastructure
        Cloud AWS Azure GCP Automation Scripting Linux
        Monitoring Terraform Ansible System Administration
        Kỹ sư DevOps Tự động hóa Triển khai
    """,
    "Cloud Architect": """
        Cloud Architecture AWS Azure GCP Infrastructure as Code
        Serverless Microservices Container Orchestration Scalability
        High Availability Disaster Recovery Security Compliance
        Kiến trúc đám mây Cloud Solution
    """,
    "System Administrator": """
        System Administration Linux Windows Server Networking
        Active Directory DNS DHCP VMware Monitoring Backup
        Security Patching Troubleshooting IT Infrastructure
        Quản trị hệ thống Quản trị máy chủ
    """,
    "Network Engineer": """
        Networking Cisco Router Switch TCP/IP VPN Firewall
        OSPF BGP VLANs WAN LAN WiFi Network Security
        Packet Tracer Wireshark Network Monitoring NOC
        Kỹ sư mạng Quản trị mạng
    """,

    # ── SECURITY ──────────────────────────────────────────────────────────
    "Cybersecurity Analyst": """
        Cybersecurity Information Security Network Security Penetration Testing
        Ethical Hacking Security Audit Risk Assessment SIEM
        Firewall Encryption Incident Response Compliance
        An ninh mạng Bảo mật Phân tích bảo mật
    """,
    "Security Engineer": """
        Security Engineering Cloud Security Zero Trust SOC
        SIEM Encryption PKI Vulnerability Management DevSecOps
        Identity Access Management Threat Modeling
        Kỹ sư bảo mật Bảo mật ứng dụng
    """,

    # ── ENGINEERING ───────────────────────────────────────────────────────
    "Robotics Engineer": """
        Robotics ROS Robot Operating System Control Systems
        Embedded C++ Sensors Actuators Automation Computer Vision
        Mechatronics Simulation SLAM Path Planning
        Kỹ sư robot Tự động hóa robot
    """,
    "Embedded Engineer": """
        Embedded Systems C C++ Microcontroller RTOS Firmware
        Arduino STM32 PCB Electronics Signal Processing
        IoT UART SPI I2C Low-level Programming
        Kỹ sư nhúng Lập trình vi điều khiển
    """,
    "IoT Engineer": """
        Internet of Things IoT Sensors MQTT BLE WiFi Cloud
        Raspberry Pi Arduino Edge Computing Python C
        Smart Devices Protocol Firmware Integration
        Kỹ sư IoT Internet vạn vật
    """,
    "Electrical Engineer": """
        Electrical Engineering Circuit Design Power Systems
        PLC SCADA AutoCAD MATLAB Embedded Control
        High Voltage Renewable Energy Motor Drive
        Kỹ sư điện Thiết kế mạch điện
    """,
    "Mechanical Engineer": """
        Mechanical Engineering CAD SolidWorks ANSYS FEA
        Thermodynamics Fluid Mechanics Manufacturing
        Product Design Simulation Materials Science
        Kỹ sư cơ khí Thiết kế cơ khí
    """,
    "Civil Engineer": """
        Civil Engineering Structural Analysis AutoCAD Revit
        Construction Project Management Geotechnical
        Bridge Road Foundation Hydraulics Surveying
        Kỹ sư xây dựng Kết cấu công trình
    """,
    "Manufacturing Engineer": """
        Manufacturing Lean Six Sigma Process Optimization
        CNC Machining Production Planning CAD CAM
        Quality Control ISO Standards Kaizen
        Kỹ sư sản xuất Tối ưu quy trình
    """,
    "Quality Engineer": """
        Quality Engineering QA QC Inspection ISO IATF
        SPC Root Cause Analysis FMEA Control Plan
        Metrology Testing Standards Certification
        Kỹ sư chất lượng Kiểm soát chất lượng
    """,
    "Production Manager": """
        Production Management Manufacturing Operations Leadership
        KPI OEE Lean Scheduling Resource Planning
        Team Management Safety Cost Reduction
        Quản lý sản xuất Quản lý nhà máy
    """,

    # ── IT SUPPORT ────────────────────────────────────────────────────────
    "IT Support": """
        IT Support Helpdesk Troubleshooting Windows Hardware
        Software Installation Networking Ticketing ITIL
        User Support Desktop Support Remote Assistance
        Hỗ trợ IT Kỹ thuật viên IT
    """,

    # ── DESIGN ────────────────────────────────────────────────────────────
    "UI/UX Designer": """
        User Experience User Interface Design Figma Adobe XD
        Prototyping Wireframe Visual Design Interaction Design
        Usability User Research Design Thinking Sketch
        Thiết kế giao diện Trải nghiệm người dùng UX UI
    """,
    "Graphic Designer": """
        Graphic Design Adobe Photoshop Illustrator InDesign
        Visual Design Branding Logo Design Typography
        Print Design Digital Design Creative Layout
        Thiết kế đồ họa Thiết kế hình ảnh
    """,
    "Motion Designer": """
        Motion Design After Effects Animation Video Editing
        Motion Graphics Typography Premiere Pro 3D Animation
        Visual Effects Compositing Storytelling
        Thiết kế chuyển động Hoạt ảnh
    """,
    "Product Designer": """
        Product Design UX Figma Design Systems User Research
        Prototyping A/B Testing Cross-functional Team
        Visual Design Interaction Design Mobile Web
        Thiết kế sản phẩm Nghiên cứu người dùng
    """,
    "Architect": """
        Architecture AutoCAD Revit SketchUp 3D Rendering
        Structural Design Interior Space Planning Building Code
        Construction Urban Planning Sustainable Design
        Kiến trúc sư Thiết kế công trình
    """,
    "3D Artist": """
        3D Art Blender Maya Cinema 4D ZBrush 3D Modeling
        Texturing Rigging Rendering Lighting Animation
        Game Art Product Visualization VFX
        Nghệ sĩ 3D Thiết kế 3D
    """,

    # ── MARKETING / MEDIA ─────────────────────────────────────────────────
    "Digital Marketer": """
        Digital Marketing SEO SEM Paid Ads Google Ads Facebook
        Content Marketing Email Marketing Analytics Funnel
        A/B Testing Conversion Social Media Performance Marketing
        Marketing kỹ thuật số Quảng cáo trực tuyến
    """,
    "Content Creator": """
        Content Creation YouTube TikTok Instagram Video Podcast
        Writing Storytelling Editing Social Media Engagement
        Brand Collaboration Monetization Creative
        Người tạo nội dung Sáng tạo nội dung
    """,
    "Copywriter": """
        Copywriting Marketing Copy Advertising Sales Copy
        SEO Writing Brand Voice Persuasion Content Strategy
        Email Copy Landing Page Creative Writing
        Viết quảng cáo Viết nội dung marketing
    """,
    "PR Manager": """
        Public Relations Media Relations Press Release
        Crisis Communication Brand Reputation Stakeholders
        Events Sponsorship Journalist Communication
        Quản lý quan hệ công chúng PR
    """,
    "Brand Manager": """
        Brand Management Marketing Strategy Brand Identity
        Campaign Management Market Research Consumer Insight
        Brand Equity Budget Management Analytics
        Quản lý thương hiệu Xây dựng thương hiệu
    """,
    "Social Media Manager": """
        Social Media Facebook Instagram TikTok LinkedIn Content
        Community Management Scheduling Analytics Ads
        Influencer Engagement Growth Strategy
        Quản lý mạng xã hội Truyền thông xã hội
    """,
    "Journalist": """
        Journalism News Reporting Writing Research Investigation
        Media Broadcasting Interviewing Fact-checking Editing
        Press Photography Multimedia Storytelling
        Nhà báo Phóng viên Biên tập
    """,
    "Video Editor": """
        Video Editing Premiere Pro Final Cut Pro After Effects
        Color Grading Audio Mixing Motion Graphics Storytelling
        YouTube Social Media Documentary Short Film
        Dựng phim Biên tập video
    """,

    # ── BUSINESS / OPERATIONS ─────────────────────────────────────────────
    "Product Manager": """
        Product Management Roadmap Strategy Agile Scrum
        User Stories Requirements PRD Stakeholder Management
        Market Research Analytics Product Launch Business
        Quản lý sản phẩm Chiến lược Phát triển sản phẩm
    """,
    "Business Analyst": """
        Business Analysis Requirements Gathering Process Improvement
        SQL Data Analysis Documentation Stakeholder Management
        Agile JIRA Workflow Project Management
        Phân tích kinh doanh Phân tích quy trình
    """,
    "Project Manager": """
        Project Management PMP Agile Scrum Waterfall Planning
        Risk Management Budget Schedule Stakeholders JIRA
        Coordination Delivery Leadership Team Management
        Quản lý dự án Điều phối dự án
    """,
    "Sales Manager": """
        Sales Management B2B B2C CRM Pipeline Lead Generation
        Sales Strategy Negotiation Revenue Growth
        Account Management Team Leadership Customer Relations
        Quản lý bán hàng Phát triển doanh số
    """,
    "Account Manager": """
        Account Management Client Relations Customer Success
        CRM Upselling Renewals Onboarding Communication
        B2B Revenue Retention Stakeholder
        Quản lý khách hàng Quan hệ khách hàng
    """,
    "Strategy Analyst": """
        Strategy Analysis Business Strategy Market Analysis
        Research Presentation Consulting Frameworks
        Competitive Analysis Growth Planning Excel PowerPoint
        Phân tích chiến lược Tư vấn chiến lược
    """,
    "Operations Analyst": """
        Operations Analysis Process Optimization Excel KPI
        Lean Six Sigma Workflow Automation Reporting
        Supply Chain Logistics Cost Reduction
        Phân tích vận hành Tối ưu quy trình
    """,
    "Startup Founder": """
        Startup Entrepreneurship Business Founding CEO
        Pitching Fundraising Investors Product Market Fit
        Team Building Leadership Vision Strategy Innovation
        Nhà sáng lập Startup Khởi nghiệp
    """,

    # ── FINANCE ───────────────────────────────────────────────────────────
    "Financial Analyst": """
        Financial Analysis Investment Financial Modeling Excel
        Forecasting Budgeting Financial Reporting Valuation
        Risk Management Corporate Finance Accounting DCF
        Phân tích tài chính Đầu tư Mô hình tài chính
    """,
    "Quant Analyst": """
        Quantitative Finance Math Statistics Python R Derivatives
        Algorithmic Trading Risk Modeling Stochastic Calculus
        Portfolio Optimization Backtesting Statistical Arbitrage
        Phân tích định lượng Tài chính toán học
    """,
    "Accountant": """
        Accounting Financial Statements Tax GAAP IFRS Excel
        General Ledger Payroll Bookkeeping Audit Compliance
        ERP SAP Reconciliation Balance Sheet
        Kế toán Kế toán tài chính
    """,
    "Auditor": """
        Auditing External Internal Audit IFRS Risk Assessment
        Compliance Controls Testing Sampling Evidence
        Big Four CPA Audit Report Governance
        Kiểm toán Kiểm toán nội bộ
    """,
    "Investment Banker": """
        Investment Banking M&A IPO Capital Markets Valuation
        Excel Financial Modeling Pitchbook Deal Execution
        Equity Debt Restructuring Client Advisory
        Ngân hàng đầu tư Tư vấn tài chính
    """,
    "Risk Manager": """
        Risk Management Market Credit Operational Risk VaR
        Compliance Regulatory Basel Python Statistics
        Stress Testing Risk Reporting COSO ERM
        Quản lý rủi ro Kiểm soát rủi ro
    """,
    "Fintech Engineer": """
        Fintech Financial Technology Payment Systems API Banking
        Python Cloud Security Microservices Open Banking
        Blockchain Digital Wallet KYC AML Regulation
        Kỹ sư Fintech Công nghệ tài chính
    """,

    # ── HEALTHCARE ────────────────────────────────────────────────────────
    "Doctor": """
        Medicine Clinical Diagnosis Treatment Patient Care
        Medical Records Lab Results Surgery Prescription
        Hospital Specialist General Practice Healthcare
        Bác sĩ Y khoa Chẩn đoán và điều trị
    """,
    "Nurse": """
        Nursing Patient Care Clinical Assessment Medication
        EMR Vital Signs IV Therapy Wound Care Monitoring
        Hospital Ward ICU ER Community Health
        Y tá Điều dưỡng Chăm sóc bệnh nhân
    """,
    "Pharmacist": """
        Pharmacy Drug Therapy Pharmacology Counseling
        Dispensing Drug Interaction Clinical Pharmacy
        Hospital Community Compounding Medication Review
        Dược sĩ Dược lâm sàng
    """,
    "Health Informatics Specialist": """
        Health Informatics EHR HL7 FHIR Medical Data
        Healthcare IT Analytics Clinical Workflow HIS LIS
        Electronic Medical Records Interoperability
        Chuyên gia y tế số Tin học y tế
    """,

    # ── LEGAL ─────────────────────────────────────────────────────────────
    "Lawyer": """
        Law Legal Services Litigation Contract Drafting
        Legal Research Court Corporate Law Criminal
        Negotiation Dispute Resolution Compliance
        Luật sư Tư vấn pháp lý
    """,
    "Legal Counsel": """
        In-House Legal Counsel Corporate Law Contracts
        Compliance Risk M&A Employment Law IP Regulatory
        Business Legal Strategy Negotiation
        Cố vấn pháp lý Pháp chế doanh nghiệp
    """,
    "Compliance Officer": """
        Compliance Regulatory AML KYC Risk Management
        Audit Policy Governance GDPR ISO Internal Control
        Financial Services Legal Reporting Monitoring
        Chuyên viên tuân thủ Pháp chế
    """,

    # ── HR ────────────────────────────────────────────────────────────────
    "HR Manager": """
        Human Resources Recruitment Talent Acquisition Employee Relations
        Performance Management Compensation Benefits Training Development
        HR Policies Labor Law Organizational Development HRIS
        Quản lý nhân sự Tuyển dụng Đào tạo
    """,
    "Talent Acquisition Specialist": """
        Talent Acquisition Recruiting Sourcing LinkedIn ATS
        Job Description Interview Assessment Offer Negotiation
        Employer Branding Headhunting Pipeline Diversity
        Tuyển dụng Chuyên viên tuyển dụng
    """,
    "HR Data Analyst": """
        People Analytics HR Analytics SQL Python Dashboard
        Workforce Planning Retention Attrition Turnover
        Headcount Survey HRIS Tableau Statistical Analysis
        Phân tích nhân sự HR Analytics
    """,

    # ── LOGISTICS / SUPPLY CHAIN ─────────────────────────────────────────
    "Supply Chain Manager": """
        Supply Chain Management Procurement Inventory Logistics
        ERP SAP Lean Supplier Relations Demand Planning
        Warehousing Distribution Cost Optimization
        Quản lý chuỗi cung ứng Logistics
    """,
    "Logistics Coordinator": """
        Logistics Freight Shipping Transportation WMS
        Customs Clearance Documentation Import Export
        Carrier Partner Coordination 3PL Excel
        Điều phối logistics Vận chuyển hàng hóa
    """,

    # ── EDUCATION ─────────────────────────────────────────────────────────
    "AI Lecturer": """
        AI Education Teaching Machine Learning Deep Learning
        University Research Curriculum Course Design
        Academic Publication Student Mentoring STEM
        Giảng viên AI Giảng dạy trí tuệ nhân tạo
    """,
    "STEM Teacher": """
        STEM Education Science Technology Engineering Math
        Teaching Curriculum Design Classroom Lab
        Experiential Learning Assessment K-12 High School
        Giáo viên STEM Dạy học
    """,
    "E-learning Designer": """
        E-learning Instructional Design Online Learning LMS
        Articulate Storyline Video Production SCORM Moodle
        Curriculum Storyboard Adult Learning Engagement
        Thiết kế e-learning Đào tạo trực tuyến
    """,
    "Training Manager": """
        Training Development L&D Learning Design Facilitation
        Needs Analysis LMS Program Management Coaching
        Skills Assessment Onboarding Leadership Development
        Trưởng phòng đào tạo Phát triển nhân lực
    """,
}


VI_MAP = {
    "à": "a", "á": "a", "ả": "a", "ã": "a", "ạ": "a",
    "ă": "a", "ằ": "a", "ắ": "a", "ẳ": "a", "ẵ": "a", "ặ": "a",
    "â": "a", "ầ": "a", "ấ": "a", "ẩ": "a", "ẫ": "a", "ậ": "a",
    "è": "e", "é": "e", "ẻ": "e", "ẽ": "e", "ẹ": "e",
    "ê": "e", "ề": "e", "ế": "e", "ể": "e", "ễ": "e", "ệ": "e",
    "ì": "i", "í": "i", "ỉ": "i", "ĩ": "i", "ị": "i",
    "ò": "o", "ó": "o", "ỏ": "o", "õ": "o", "ọ": "o",
    "ô": "o", "ồ": "o", "ố": "o", "ổ": "o", "ỗ": "o", "ộ": "o",
    "ơ": "o", "ờ": "o", "ớ": "o", "ở": "o", "ỡ": "o", "ợ": "o",
    "ù": "u", "ú": "u", "ủ": "u", "ũ": "u", "ụ": "u",
    "ư": "u", "ừ": "u", "ứ": "u", "ử": "u", "ữ": "u", "ự": "u",
    "ỳ": "y", "ý": "y", "ỷ": "y", "ỹ": "y", "ỵ": "y",
    "đ": "d"
}

def normalize_text(text: str) -> str:
    """Lowercase, remove accents, special chars"""

    if not text:
        return ""

    text = text.lower().strip()

    normalized = ""
    for c in text:
        normalized += VI_MAP.get(c, c)

    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)

    return normalized.strip()


# ======================================================
# EMBEDDING ENGINE
# ======================================================

class EmbeddingEngine:
    """
    Singleton embedding engine
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EmbeddingEngine, cls).__new__(cls)
        return cls._instance

    def __init__(self):

        if hasattr(self, "_initialized"):
            return

        print("[Embedding] Loading model...")

        self.model = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2"
        )

        self.dimension = self.model.get_sentence_embedding_dimension()

        self.career_names = list(CAREER_CORPUS.keys())
        self.career_texts = [
            normalize_text(v) for v in CAREER_CORPUS.values()
        ]

        self.index = None
        self.embeddings = None

        self._build_index()

        self._initialized = True

        print("[Embedding] Ready.")


    # --------------------------------------------------

    def _embed(self, text: str) -> np.ndarray:

        text = normalize_text(text)

        if not text:
            return np.zeros(self.dimension, dtype=np.float32)

        vec = self.model.encode(text)

        vec = vec.astype(np.float32)

        if _FAISS_AVAILABLE:
            faiss.normalize_L2(vec.reshape(1, -1))
        else:
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm

        return vec


    # --------------------------------------------------

    def _build_index(self):

        print("[Embedding] Building FAISS index...")

        vectors = []

        for txt in self.career_texts:
            vectors.append(self._embed(txt))

        self.embeddings = np.vstack(vectors)

        if _FAISS_AVAILABLE:
            self.index = faiss.IndexFlatIP(self.dimension)
            self.index.add(self.embeddings)
        else:
            self.index = None  # Will use numpy cosine search

        print(f"[Embedding] Indexed {len(vectors)} careers (faiss={'on' if _FAISS_AVAILABLE else 'off'}).")


    # --------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 5
    ) -> List[Dict]:

        if not query:
            return []

        q_vec = self._embed(query).reshape(1, -1)

        if self.index is not None:
            scores, ids = self.index.search(
                q_vec,
                min(top_k, len(self.career_names))
            )
            results = []
            for i, s in zip(ids[0], scores[0]):
                results.append({
                    "career": self.career_names[i],
                    "similarity": round(float(s), 4)
                })
        else:
            # Numpy cosine fallback
            sims = self.embeddings.dot(q_vec.T).flatten()
            top_idx = np.argsort(sims)[::-1][:min(top_k, len(self.career_names))]
            results = [
                {"career": self.career_names[i], "similarity": round(float(sims[i]), 4)}
                for i in top_idx
            ]

        return results


    # --------------------------------------------------

    def match_profile(
        self,
        processed_profile: Dict,
        top_k: int = 5,
        candidates: List[str] = None
    ) -> List[Dict]:

        parts = []

        parts.append(processed_profile.get("goal_cleaned", ""))
        parts.append(processed_profile.get("chat_summary", ""))

        parts.extend(processed_profile.get("skill_tags", []))
        parts.extend(processed_profile.get("interest_tags", []))

        combined = " ".join(parts)

        # Retrieve enough results to cover filtering by candidates
        fetch_k = len(self.career_names) if candidates else top_k
        results = self.search(combined, top_k=fetch_k)

        if candidates:
            candidate_set = set(candidates)
            results = [r for r in results if r["career"] in candidate_set]

        return results[:top_k]


# ======================================================
# PUBLIC API
# ======================================================

_engine = None


def get_engine() -> EmbeddingEngine:
    global _engine

    if _engine is None:
        _engine = EmbeddingEngine()

    return _engine


def match_careers(
    processed_profile: Dict,
    top_k: int = 5,
    candidates: List[str] = None
) -> List[Dict]:

    engine = get_engine()

    return engine.match_profile(processed_profile, top_k, candidates)


# ======================================================
# TEST
# ======================================================

if __name__ == "__main__":

    print("\n" + "=" * 70)
    print("EMBEDDING ENGINE TEST")
    print("=" * 70)

    engine = get_engine()

    samples = [

        {
            "goal_cleaned": "muon lam ky su ai",
            "chat_summary": "thich hoc may va du lieu",
            "skill_tags": ["Python", "Machine Learning"],
            "interest_tags": ["IT"]
        },

        {
            "goal_cleaned": "thiet ke giao dien web",
            "chat_summary": "thich sang tao",
            "skill_tags": ["UI Design", "Figma"],
            "interest_tags": ["Design"]
        },

        {
            "goal_cleaned": "lam marketing online",
            "chat_summary": "seo va quang cao",
            "skill_tags": ["SEO", "Content"],
            "interest_tags": ["Business"]
        },

    ]


    for i, p in enumerate(samples, 1):

        print(f"\n--- TEST {i} ---")

        results = engine.match_profile(p)

        for r in results:
            print(r)

    print("\nDONE.")
