"""
GrantMirror-AI: Offline Horizon Europe Call Database
Comprehensive database with 30+ real calls across all clusters.
Auto-syncs with live API when available.
"""
import json
import re
from typing import List, Dict, Tuple, Optional

# ═══════════════════════════════════════════════════════════
# COMPREHENSIVE HORIZON EUROPE CALLS DATABASE
# ═══════════════════════════════════════════════════════════
HORIZON_CALLS_DB: List[Dict] = [
    # ── CLUSTER 1: Health ──
    {
        "call_id": "HORIZON-HLTH-2025-DISEASE-01",
        "title": "Tackling diseases 2025",
        "status": "Open",
        "destination": "Cluster 1 – Health",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-04-15",
        "budget_per_project": "€4-6M",
        "keywords": ["health", "disease", "therapy", "clinical", "diagnostics",
                      "cancer", "infection", "rare disease", "precision medicine",
                      "biomarker", "drug", "treatment", "patient", "medical"],
        "expected_outcomes": "New therapeutic approaches, diagnostic tools, and disease models "
                             "contributing to improved patient outcomes and healthcare systems.",
        "scope": "Development of novel therapies, diagnostics, and digital tools for major diseases "
                 "including cancer, cardiovascular, neurodegenerative, and rare diseases.",
    },
    {
        "call_id": "HORIZON-HLTH-2025-TOOLS-01",
        "title": "Tools, technologies and digital solutions for health 2025",
        "status": "Open",
        "destination": "Cluster 1 – Health",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-04-15",
        "budget_per_project": "€3-5M",
        "keywords": ["digital health", "AI health", "medical device", "eHealth",
                      "telemedicine", "wearable", "health data", "imaging",
                      "bioinformatics", "personalised medicine", "EHR"],
        "expected_outcomes": "Innovative digital health solutions, AI-driven diagnostics, and "
                             "next-generation medical devices for improved healthcare delivery.",
        "scope": "Digital tools, AI/ML for health, advanced imaging, point-of-care diagnostics, "
                 "health data integration and interoperability.",
    },
    {
        "call_id": "HORIZON-HLTH-2025-ENVHLTH-01",
        "title": "Environment and health 2025",
        "status": "Open",
        "destination": "Cluster 1 – Health",
        "action_types": ["RIA"],
        "deadline": "2025-04-15",
        "budget_per_project": "€5-7M",
        "keywords": ["environmental health", "pollution", "exposome", "climate health",
                      "air quality", "toxicology", "chemical risk", "One Health",
                      "zoonotic", "antimicrobial resistance", "AMR"],
        "expected_outcomes": "Better understanding of environmental impacts on health, new risk "
                             "assessment tools, and integrated One Health approaches.",
        "scope": "Environmental determinants of health, exposome research, AMR, climate-health "
                 "nexus, chemical safety, and One Health implementation.",
    },
    {
        "call_id": "HORIZON-HLTH-2025-CARE-01",
        "title": "Ensuring access to innovative, sustainable and high-quality health care 2025",
        "status": "Forthcoming",
        "destination": "Cluster 1 – Health",
        "action_types": ["RIA", "CSA"],
        "deadline": "2025-09-11",
        "budget_per_project": "€3-5M",
        "keywords": ["healthcare system", "health equity", "access", "sustainability",
                      "primary care", "health workforce", "integrated care", "prevention"],
        "expected_outcomes": "Scalable models for equitable, efficient and resilient healthcare systems.",
        "scope": "Health system innovation, integrated care models, workforce planning, "
                 "prevention strategies, and health equity interventions.",
    },

    # ── CLUSTER 2: Culture, Creativity and Inclusive Society ──
    {
        "call_id": "HORIZON-CL2-2025-DEMOCRACY-01",
        "title": "Democracy and governance 2025",
        "status": "Open",
        "destination": "Cluster 2 – Culture, Creativity and Inclusive Society",
        "action_types": ["RIA", "CSA"],
        "deadline": "2025-02-19",
        "budget_per_project": "€2-3M",
        "keywords": ["democracy", "governance", "participation", "rule of law",
                      "disinformation", "media", "polarisation", "civic engagement",
                      "European values", "trust", "institutions"],
        "expected_outcomes": "Evidence-based solutions to strengthen democratic governance, "
                             "counter disinformation, and enhance citizen participation.",
        "scope": "Democratic innovation, counter-disinformation tools, civic tech, media literacy, "
                 "governance models, and societal resilience.",
    },
    {
        "call_id": "HORIZON-CL2-2025-HERITAGE-01",
        "title": "Cultural heritage and cultural and creative industries 2025",
        "status": "Open",
        "destination": "Cluster 2 – Culture, Creativity and Inclusive Society",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-02-19",
        "budget_per_project": "€2-4M",
        "keywords": ["cultural heritage", "creative industries", "digitisation", "arts",
                      "museum", "archaeology", "restoration", "cultural tourism",
                      "3D scanning", "immersive", "VR heritage"],
        "expected_outcomes": "Innovative approaches to cultural heritage preservation, digital "
                             "access, and growth of cultural and creative industries.",
        "scope": "Heritage digitisation, creative technology, cultural participation, "
                 "sustainable cultural tourism, and CCI business models.",
    },
    {
        "call_id": "HORIZON-CL2-2025-TRANSFORMATIONS-01",
        "title": "Social and economic transformations 2025",
        "status": "Open",
        "destination": "Cluster 2 – Culture, Creativity and Inclusive Society",
        "action_types": ["RIA"],
        "deadline": "2025-02-19",
        "budget_per_project": "€2-3M",
        "keywords": ["social transformation", "inequality", "migration", "education",
                      "skills", "labour market", "inclusion", "gender equality",
                      "youth", "ageing", "welfare"],
        "expected_outcomes": "New knowledge on social and economic transformations for inclusive "
                             "and resilient European societies.",
        "scope": "Social inequalities, future of work, migration, education systems, "
                 "demographic change, and welfare state innovation.",
    },

    # ── CLUSTER 3: Civil Security for Society ──
    {
        "call_id": "HORIZON-CL3-2025-FCT-01",
        "title": "Fighting crime and terrorism 2025",
        "status": "Open",
        "destination": "Cluster 3 – Civil Security for Society",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-11-20",
        "budget_per_project": "€3-5M",
        "keywords": ["security", "crime", "terrorism", "cybercrime", "forensics",
                      "law enforcement", "border", "CBRN", "organised crime",
                      "counter-terrorism", "surveillance", "intelligence"],
        "expected_outcomes": "Advanced tools and methods for law enforcement and security "
                             "practitioners to prevent, detect, and investigate crime and terrorism.",
        "scope": "Digital forensics, CBRN detection, border security tech, cybersecurity, "
                 "predictive policing ethics, and security practitioner tools.",
    },
    {
        "call_id": "HORIZON-CL3-2025-DRS-01",
        "title": "Disaster-resilient society 2025",
        "status": "Forthcoming",
        "destination": "Cluster 3 – Civil Security for Society",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-11-20",
        "budget_per_project": "€3-5M",
        "keywords": ["disaster", "resilience", "emergency", "crisis management",
                      "natural hazard", "flood", "earthquake", "wildfire",
                      "early warning", "civil protection", "climate adaptation"],
        "expected_outcomes": "Improved disaster preparedness, response, and recovery capabilities "
                             "for European communities and critical infrastructure.",
        "scope": "Multi-hazard early warning, crisis communication, community resilience, "
                 "critical infrastructure protection, and climate-related disaster management.",
    },

    # ── CLUSTER 4: Digital, Industry and Space ──
    {
        "call_id": "HORIZON-CL4-2025-HUMAN-01",
        "title": "A human-centred and ethical development of digital and industrial technologies 2025",
        "status": "Open",
        "destination": "Cluster 4 – Digital, Industry and Space",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-02-19",
        "budget_per_project": "€3-5M",
        "keywords": ["AI", "artificial intelligence", "digital", "human-centric",
                      "ethics", "trustworthy AI", "HPC", "robotics", "IoT",
                      "data", "cloud", "edge computing", "cybersecurity",
                      "digital twin", "quantum", "semiconductor"],
        "expected_outcomes": "Human-centric digital technologies that are trustworthy, sustainable, "
                             "and support European digital sovereignty.",
        "scope": "AI systems, robotics, IoT, data spaces, cybersecurity, digital twins, "
                 "and human-AI interaction with ethical considerations.",
    },
    {
        "call_id": "HORIZON-CL4-2025-DIGITAL-01",
        "title": "Digital and emerging technologies 2025",
        "status": "Open",
        "destination": "Cluster 4 – Digital, Industry and Space",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-02-19",
        "budget_per_project": "€3-6M",
        "keywords": ["digital", "emerging technology", "6G", "photonics", "electronics",
                      "quantum computing", "blockchain", "metaverse", "XR",
                      "next generation internet", "open source", "software"],
        "expected_outcomes": "Breakthrough digital and emerging technologies ensuring European "
                             "competitiveness and digital leadership.",
        "scope": "Next-gen computing, 6G, photonics, quantum technologies, immersive tech, "
                 "open source ecosystems, and electronic components.",
    },
    {
        "call_id": "HORIZON-CL4-2025-TWIN-01",
        "title": "Global challenges and European industrial competitiveness – Twin transition 2025",
        "status": "Open",
        "destination": "Cluster 4 – Digital, Industry and Space",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-02-19",
        "budget_per_project": "€4-8M",
        "keywords": ["manufacturing", "industry 4.0", "circular economy", "materials",
                      "advanced materials", "nano", "process industry", "raw materials",
                      "twin transition", "green manufacturing", "industrial symbiosis",
                      "supply chain", "automation", "3D printing"],
        "expected_outcomes": "Advanced manufacturing, materials, and processes supporting the "
                             "twin green and digital transition of European industry.",
        "scope": "Smart manufacturing, advanced materials, circular processes, industrial "
                 "digitalisation, and resource-efficient production systems.",
    },
    {
        "call_id": "HORIZON-CL4-2025-SPACE-01",
        "title": "Space research and innovation 2025",
        "status": "Forthcoming",
        "destination": "Cluster 4 – Digital, Industry and Space",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-03-18",
        "budget_per_project": "€2-4M",
        "keywords": ["space", "satellite", "Earth observation", "Copernicus", "Galileo",
                      "space debris", "launch", "in-orbit", "SSA",
                      "space weather", "GNSS", "remote sensing"],
        "expected_outcomes": "Competitive and sustainable European space sector with innovative "
                             "applications and services.",
        "scope": "Earth observation applications, satellite communication, space situational "
                 "awareness, in-orbit services, and space technology development.",
    },

    # ── CLUSTER 5: Climate, Energy and Mobility ──
    {
        "call_id": "HORIZON-CL5-2025-D1-01",
        "title": "Climate science and solutions 2025",
        "status": "Open",
        "destination": "Cluster 5 – Climate, Energy and Mobility",
        "action_types": ["RIA"],
        "deadline": "2025-03-04",
        "budget_per_project": "€4-7M",
        "keywords": ["climate", "climate change", "carbon", "greenhouse gas", "GHG",
                      "climate model", "adaptation", "mitigation", "net zero",
                      "carbon capture", "CCUS", "Paris agreement", "climate neutral"],
        "expected_outcomes": "Improved climate science, modelling and prediction capabilities, "
                             "and innovative climate change mitigation/adaptation solutions.",
        "scope": "Climate system understanding, Earth system modelling, carbon cycle, "
                 "tipping points, nature-based solutions, and climate services.",
    },
    {
        "call_id": "HORIZON-CL5-2025-D2-01",
        "title": "Cross-sectoral solutions for the climate transition 2025",
        "status": "Open",
        "destination": "Cluster 5 – Climate, Energy and Mobility",
        "action_types": ["RIA", "IA", "CSA"],
        "deadline": "2025-03-04",
        "budget_per_project": "€3-6M",
        "keywords": ["energy transition", "circular economy", "urban", "community",
                      "social innovation", "behaviour change", "climate governance",
                      "just transition", "citizen", "prosumer", "energy community"],
        "expected_outcomes": "Cross-sectoral solutions enabling systemic change for climate "
                             "neutrality and resilience.",
        "scope": "Socio-economic transitions, governance innovation, citizen engagement, "
                 "circular solutions, and just transition pathways.",
    },
    {
        "call_id": "HORIZON-CL5-2025-D3-01",
        "title": "Sustainable, secure and competitive energy supply 2025",
        "status": "Open",
        "destination": "Cluster 5 – Climate, Energy and Mobility",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-03-04",
        "budget_per_project": "€3-8M",
        "keywords": ["renewable energy", "solar", "wind", "hydrogen", "fuel cell",
                      "battery", "energy storage", "grid", "smart grid",
                      "geothermal", "ocean energy", "bioenergy", "nuclear fusion",
                      "green hydrogen", "electrolyser", "power-to-X"],
        "expected_outcomes": "Breakthrough clean energy technologies and systems for a secure, "
                             "affordable and sustainable European energy supply.",
        "scope": "Renewable energy technologies, energy storage, hydrogen value chain, "
                 "smart grids, and integrated energy systems.",
    },
    {
        "call_id": "HORIZON-CL5-2025-D4-01",
        "title": "Efficient, sustainable and inclusive energy use 2025",
        "status": "Open",
        "destination": "Cluster 5 – Climate, Energy and Mobility",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-03-04",
        "budget_per_project": "€3-5M",
        "keywords": ["energy efficiency", "building", "heating", "cooling", "HVAC",
                      "insulation", "renovation", "smart building", "district heating",
                      "industrial energy", "heat pump", "energy poverty"],
        "expected_outcomes": "Solutions for radically improved energy efficiency in buildings, "
                             "industry and communities.",
        "scope": "Building energy systems, deep renovation, industrial energy efficiency, "
                 "district energy, and energy poverty alleviation.",
    },
    {
        "call_id": "HORIZON-CL5-2025-D5-01",
        "title": "Clean and competitive solutions for all transport modes 2025",
        "status": "Open",
        "destination": "Cluster 5 – Climate, Energy and Mobility",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-04-08",
        "budget_per_project": "€3-7M",
        "keywords": ["transport", "mobility", "electric vehicle", "EV", "autonomous",
                      "aviation", "maritime", "rail", "logistics", "MaaS",
                      "connected", "sustainable transport", "zero emission",
                      "urban mobility", "freight"],
        "expected_outcomes": "Clean, connected and competitive transport solutions across all "
                             "modes contributing to climate neutrality.",
        "scope": "Zero-emission vehicles, autonomous mobility, sustainable aviation fuels, "
                 "smart logistics, multimodal transport, and urban mobility solutions.",
    },

    # ── CLUSTER 6: Food, Bioeconomy, Natural Resources, Agriculture, Environment ──
    {
        "call_id": "HORIZON-CL6-2025-BIODIV-01",
        "title": "Biodiversity and ecosystem services 2025",
        "status": "Open",
        "destination": "Cluster 6 – Food, Bioeconomy, Natural Resources",
        "action_types": ["RIA", "IA", "CSA"],
        "deadline": "2025-02-19",
        "budget_per_project": "€3-6M",
        "keywords": ["biodiversity", "ecosystem", "nature", "conservation",
                      "pollinator", "marine", "forest", "soil", "water",
                      "restoration", "monitoring", "eDNA", "protected area",
                      "nature-based solutions", "invasive species"],
        "expected_outcomes": "Science-based solutions for halting biodiversity loss, restoring "
                             "ecosystems, and valuing ecosystem services.",
        "scope": "Biodiversity monitoring, ecosystem restoration, nature-based solutions, "
                 "marine and terrestrial conservation, and biodiversity-friendly land use.",
    },
    {
        "call_id": "HORIZON-CL6-2025-FARM2FORK-01",
        "title": "Fair, healthy and environment-friendly food systems 2025",
        "status": "Open",
        "destination": "Cluster 6 – Food, Bioeconomy, Natural Resources",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-02-19",
        "budget_per_project": "€4-7M",
        "keywords": ["food", "agriculture", "farming", "sustainable food", "nutrition",
                      "food safety", "food waste", "precision agriculture", "organic",
                      "agroecology", "food chain", "alternative protein", "aquaculture",
                      "livestock", "plant breeding", "crop"],
        "expected_outcomes": "Innovative food systems from farm to fork that are sustainable, "
                             "resilient, healthy and fair.",
        "scope": "Sustainable farming, food processing innovation, alternative proteins, "
                 "food waste reduction, nutrition, and food system resilience.",
    },
    {
        "call_id": "HORIZON-CL6-2025-CIRCBIO-01",
        "title": "Circular economy and bioeconomy sectors 2025",
        "status": "Open",
        "destination": "Cluster 6 – Food, Bioeconomy, Natural Resources",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-02-19",
        "budget_per_project": "€3-5M",
        "keywords": ["circular economy", "bioeconomy", "bio-based", "waste", "recycling",
                      "biomass", "bioplastic", "biofuel", "forestry", "wood",
                      "textile", "packaging", "upcycling", "industrial biotechnology"],
        "expected_outcomes": "Scalable circular and bio-based solutions reducing resource "
                             "consumption and environmental impact.",
        "scope": "Bio-based industries, circular business models, waste valorisation, "
                 "sustainable forestry, and bio-based materials and chemicals.",
    },
    {
        "call_id": "HORIZON-CL6-2025-ZEROPOLLUTION-01",
        "title": "Clean environment and zero pollution 2025",
        "status": "Open",
        "destination": "Cluster 6 – Food, Bioeconomy, Natural Resources",
        "action_types": ["RIA"],
        "deadline": "2025-02-19",
        "budget_per_project": "€3-5M",
        "keywords": ["pollution", "water", "air", "soil", "remediation",
                      "microplastic", "PFAS", "contaminant", "wastewater",
                      "drinking water", "zero pollution", "environmental monitoring"],
        "expected_outcomes": "Solutions for a toxic-free environment with zero pollution of "
                             "air, water and soil.",
        "scope": "Pollutant monitoring, remediation technologies, water treatment, "
                 "emerging contaminants, and circular water systems.",
    },

    # ── MSCA ──
    {
        "call_id": "HORIZON-MSCA-2025-DN-01",
        "title": "MSCA Doctoral Networks 2025",
        "status": "Forthcoming",
        "destination": "MSCA – Marie Skłodowska-Curie Actions",
        "action_types": ["MSCA-DN"],
        "deadline": "2025-11-27",
        "budget_per_project": "€2-4M",
        "keywords": ["doctoral", "PhD", "training", "interdisciplinary", "intersectoral",
                      "research training", "early-stage researcher", "mobility",
                      "transferable skills", "supervision", "network"],
        "expected_outcomes": "Excellent doctoral training networks producing highly-skilled "
                             "researchers with enhanced career prospects.",
        "scope": "Joint doctoral programmes with academic and non-academic partners, "
                 "structured training, intersectoral mobility, and skills development.",
    },
    {
        "call_id": "HORIZON-MSCA-2025-PF-01",
        "title": "MSCA Postdoctoral Fellowships 2025",
        "status": "Forthcoming",
        "destination": "MSCA – Marie Skłodowska-Curie Actions",
        "action_types": ["MSCA-PF"],
        "deadline": "2025-09-10",
        "budget_per_project": "€180-250K",
        "keywords": ["postdoctoral", "fellowship", "researcher mobility", "career development",
                      "knowledge transfer", "secondment", "interdisciplinary",
                      "global fellowship", "European fellowship"],
        "expected_outcomes": "Enhanced career development of experienced researchers through "
                             "international and intersectoral mobility.",
        "scope": "Individual research projects by postdoctoral researchers with mandatory "
                 "mobility, training, and knowledge transfer activities.",
    },
    {
        "call_id": "HORIZON-MSCA-2025-SE-01",
        "title": "MSCA Staff Exchanges 2025",
        "status": "Forthcoming",
        "destination": "MSCA – Marie Skłodowska-Curie Actions",
        "action_types": ["CSA"],
        "deadline": "2025-03-05",
        "budget_per_project": "€500K-1.5M",
        "keywords": ["staff exchange", "knowledge transfer", "secondment", "networking",
                      "international cooperation", "intersectoral", "innovation"],
        "expected_outcomes": "Enhanced knowledge sharing through international and intersectoral "
                             "staff exchanges.",
        "scope": "Short-term staff exchanges between academic and non-academic organisations "
                 "across countries and sectors.",
    },

    # ── ERC ──
    {
        "call_id": "ERC-2025-STG",
        "title": "ERC Starting Grants 2025",
        "status": "Forthcoming",
        "destination": "ERC – European Research Council",
        "action_types": ["ERC-StG"],
        "deadline": "2025-10-15",
        "budget_per_project": "€1.5M",
        "keywords": ["frontier research", "excellence", "PI", "principal investigator",
                      "ground-breaking", "high-risk", "fundamental", "curiosity-driven",
                      "early career", "independent researcher"],
        "expected_outcomes": "Ground-breaking frontier research by outstanding early-career "
                             "researchers establishing independent research programmes.",
        "scope": "All fields of science, engineering, and scholarship. Bottom-up, "
                 "investigator-driven. 2-7 years post-PhD.",
    },
    {
        "call_id": "ERC-2025-COG",
        "title": "ERC Consolidator Grants 2025",
        "status": "Forthcoming",
        "destination": "ERC – European Research Council",
        "action_types": ["ERC-CoG"],
        "deadline": "2025-01-22",
        "budget_per_project": "€2M",
        "keywords": ["frontier research", "consolidator", "PI", "excellence",
                      "independent", "research group", "ground-breaking",
                      "mid-career", "established researcher"],
        "expected_outcomes": "Consolidation of independent research groups by outstanding "
                             "researchers with a promising track record.",
        "scope": "All fields of science. Bottom-up. 7-12 years post-PhD.",
    },
    {
        "call_id": "ERC-2025-ADG",
        "title": "ERC Advanced Grants 2025",
        "status": "Open",
        "destination": "ERC – European Research Council",
        "action_types": ["ERC-AdG"],
        "deadline": "2025-05-29",
        "budget_per_project": "€2.5M",
        "keywords": ["frontier research", "advanced", "PI", "world-leading",
                      "excellence", "ambitious", "pioneering", "senior researcher",
                      "track record", "leadership"],
        "expected_outcomes": "Pioneering frontier research by world-leading senior researchers.",
        "scope": "All fields of science. Bottom-up. Established track record of "
                 "significant research achievements in the last 10 years.",
    },

    # ── EIC ──
    {
        "call_id": "EIC-2025-PATHFINDEROPEN-01",
        "title": "EIC Pathfinder Open 2025",
        "status": "Open",
        "destination": "EIC – European Innovation Council",
        "action_types": ["EIC-Pathfinder"],
        "deadline": "2025-03-12",
        "budget_per_project": "€3-4M",
        "keywords": ["breakthrough", "deep tech", "emerging technology", "visionary",
                      "high-risk", "proof of concept", "paradigm shift", "TRL 1-4",
                      "science-to-technology", "interdisciplinary"],
        "expected_outcomes": "Radical new technology possibilities validated through proof of "
                             "concept and early prototyping.",
        "scope": "Visionary, high-risk/high-gain research exploring novel technology directions. "
                 "Interdisciplinary consortia, TRL 1-4.",
    },
    {
        "call_id": "EIC-2025-ACCELERATOR-01",
        "title": "EIC Accelerator 2025",
        "status": "Open",
        "destination": "EIC – European Innovation Council",
        "action_types": ["EIC-Accelerator"],
        "deadline": "2025-03-12",
        "budget_per_project": "€2.5M grant + €15M equity",
        "keywords": ["startup", "scaleup", "SME", "deep tech", "market",
                      "commercialisation", "investment", "equity", "TRL 5-9",
                      "disruptive innovation", "game-changing"],
        "expected_outcomes": "High-impact innovations brought to market by startups and SMEs "
                             "with potential for rapid scale-up.",
        "scope": "Single SME/startup with disruptive innovation. Blended finance: grant for "
                 "development + equity for scale-up. TRL 5-9.",
    },
    {
        "call_id": "EIC-2025-TRANSITION-01",
        "title": "EIC Transition 2025",
        "status": "Forthcoming",
        "destination": "EIC – European Innovation Council",
        "action_types": ["RIA"],
        "deadline": "2025-05-21",
        "budget_per_project": "€2.5M",
        "keywords": ["transition", "maturation", "validation", "technology transfer",
                      "proof of concept", "business plan", "IP", "TRL 3-6",
                      "lab to market", "prototype"],
        "expected_outcomes": "Maturation and validation of novel technologies from lab to "
                             "market-ready prototypes.",
        "scope": "Validation of technologies from ERC/Pathfinder results. Business case "
                 "development, IP strategy, prototype validation. TRL 3-6.",
    },

    # ── Widening & ERA ──
    {
        "call_id": "HORIZON-WIDERA-2025-ACCESS-01",
        "title": "Widening participation and spreading excellence 2025",
        "status": "Forthcoming",
        "destination": "Widening Participation and Strengthening ERA",
        "action_types": ["CSA"],
        "deadline": "2025-10-08",
        "budget_per_project": "€1-2M",
        "keywords": ["widening", "twinning", "teaming", "ERA", "excellence",
                      "capacity building", "networking", "brain circulation",
                      "research management", "low R&I countries"],
        "expected_outcomes": "Strengthened research and innovation capacity in widening countries "
                             "through networking and knowledge transfer.",
        "scope": "Twinning partnerships, institutional reform, networking, and capacity "
                 "building in widening countries.",
    },

    # ── Missions ──
    {
        "call_id": "HORIZON-MISS-2025-CANCER-01",
        "title": "Mission Cancer – Research and Innovation actions 2025",
        "status": "Forthcoming",
        "destination": "EU Mission: Cancer",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-05-06",
        "budget_per_project": "€4-8M",
        "keywords": ["cancer", "oncology", "screening", "treatment", "prevention",
                      "survivorship", "precision oncology", "immunotherapy",
                      "tumour", "paediatric cancer", "cancer registry"],
        "expected_outcomes": "Improved cancer prevention, early detection, treatment, and "
                             "quality of life for patients and survivors.",
        "scope": "Cancer screening, novel therapies, prevention, understanding of cancer biology, "
                 "health inequalities, and quality of life.",
    },
    {
        "call_id": "HORIZON-MISS-2025-OCEAN-01",
        "title": "Mission: Restore our Ocean and Waters 2025",
        "status": "Forthcoming",
        "destination": "EU Mission: Ocean and Waters",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-06-17",
        "budget_per_project": "€3-6M",
        "keywords": ["ocean", "marine", "water", "blue economy", "fisheries",
                      "aquaculture", "plastic", "marine pollution", "coastal",
                      "deep sea", "marine biodiversity", "ocean observation"],
        "expected_outcomes": "Restored and protected ocean and water ecosystems with thriving "
                             "blue economy.",
        "scope": "Marine pollution prevention, ecosystem restoration, sustainable blue economy, "
                 "ocean digital twin, and coastal resilience.",
    },
    {
        "call_id": "HORIZON-MISS-2025-CLIMA-01",
        "title": "Mission: Adaptation to Climate Change 2025",
        "status": "Forthcoming",
        "destination": "EU Mission: Climate Adaptation",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-06-17",
        "budget_per_project": "€4-7M",
        "keywords": ["climate adaptation", "resilience", "climate risk", "vulnerability",
                      "urban adaptation", "drought", "flood risk", "heat wave",
                      "climate service", "regional adaptation", "insurance"],
        "expected_outcomes": "Regions and communities better prepared for climate change impacts "
                             "through systemic adaptation solutions.",
        "scope": "Regional climate risk assessment, adaptation pathways, nature-based solutions, "
                 "climate services, and community resilience building.",
    },
    {
        "call_id": "HORIZON-MISS-2025-SOIL-01",
        "title": "Mission: A Soil Deal for Europe 2025",
        "status": "Forthcoming",
        "destination": "EU Mission: Soil Health",
        "action_types": ["RIA", "IA"],
        "deadline": "2025-06-17",
        "budget_per_project": "€3-5M",
        "keywords": ["soil", "soil health", "land degradation", "soil carbon",
                      "soil biodiversity", "contamination", "erosion", "land use",
                      "regenerative agriculture", "soil monitoring"],
        "expected_outcomes": "Healthy soils through innovative management, monitoring, and "
                             "restoration approaches.",
        "scope": "Soil health assessment, soil carbon sequestration, contamination remediation, "
                 "and sustainable land management.",
    },
    {
        "call_id": "HORIZON-MISS-2025-CITIES-01",
        "title": "Mission: Climate-Neutral and Smart Cities 2025",
        "status": "Forthcoming",
        "destination": "EU Mission: Smart Cities",
        "action_types": ["RIA", "IA", "CSA"],
        "deadline": "2025-06-17",
        "budget_per_project": "€3-6M",
        "keywords": ["smart city", "climate neutral city", "urban", "mobility",
                      "energy", "building", "green infrastructure", "citizen",
                      "digital twin city", "urban planning", "net zero city"],
        "expected_outcomes": "Scalable solutions for climate-neutral and smart cities by 2030.",
        "scope": "Urban energy systems, sustainable mobility, green infrastructure, "
                 "citizen engagement, city digital twins, and cross-city learning.",
    },
]


# ═══════════════════════════════════════════════════════════
# SEARCH & MATCH FUNCTIONS
# ═══════════════════════════════════════════════════════════
def keyword_match_calls(
    proposal_text: str, top_k: int = 5, db: Optional[List[Dict]] = None
) -> List[Tuple[Dict, float]]:
    """Match proposal text against call database using keyword overlap."""
    if db is None:
        db = HORIZON_CALLS_DB

    proposal_lower = proposal_text.lower()
    proposal_words = set(re.findall(r'\b[a-z]{3,}\b', proposal_lower))

    scored = []
    for call in db:
        call_keywords = set(k.lower() for k in call.get("keywords", []))

        # Direct keyword hits
        hits = proposal_words & call_keywords
        keyword_score = len(hits) / max(len(call_keywords), 1)

        # Title word overlap
        title_words = set(re.findall(r'\b[a-z]{3,}\b', call.get("title", "").lower()))
        title_hits = proposal_words & title_words
        title_score = len(title_hits) / max(len(title_words), 1)

        # Scope word overlap
        scope_words = set(re.findall(r'\b[a-z]{4,}\b', call.get("scope", "").lower()))
        scope_hits = proposal_words & scope_words
        scope_score = len(scope_hits) / max(len(scope_words), 1) if scope_words else 0

        # Expected outcomes overlap
        outcome_words = set(re.findall(r'\b[a-z]{4,}\b', call.get("expected_outcomes", "").lower()))
        outcome_hits = proposal_words & outcome_words
        outcome_score = len(outcome_hits) / max(len(outcome_words), 1) if outcome_words else 0

        # Weighted combination
        combined = (keyword_score * 0.4 + title_score * 0.2 +
                    scope_score * 0.25 + outcome_score * 0.15)
        scored.append((call, combined))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def ai_match_calls(
    proposal_text: str,
    llm_fn,
    top_k: int = 5,
    db: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Use AI to match proposal to calls — returns enriched call dicts."""
    if db is None:
        db = HORIZON_CALLS_DB

    # Pre-filter with keywords to reduce LLM load
    pre_filtered = keyword_match_calls(proposal_text, top_k=min(top_k * 3, 15), db=db)

    if not pre_filtered:
        return []

    # Build call summaries for LLM
    call_summaries = []
    for i, (call, kw_score) in enumerate(pre_filtered):
        call_summaries.append(
            f"{i+1}. {call['call_id']} | {call['title']} | "
            f"Types: {', '.join(call['action_types'])} | "
            f"Scope: {call.get('scope', 'N/A')[:200]} | "
            f"Expected: {call.get('expected_outcomes', 'N/A')[:200]}"
        )

    calls_text = "\n".join(call_summaries)
    proposal_snippet = proposal_text[:4000]

    sys_prompt = (
        "You are a Horizon Europe call matching expert. "
        "Analyze the proposal and rank the most relevant calls."
    )
    usr_prompt = f"""## PROPOSAL EXCERPT:
\"\"\"
{proposal_snippet}
\"\"\"

## CANDIDATE CALLS:
{calls_text}

## TASK:
Rank the top {top_k} most relevant calls for this proposal.
For each, provide a match score (0-100) and brief justification.
Also suggest the most appropriate action type.

Respond JSON:
{{
  "matches": [
    {{
      "rank": 1,
      "call_index": <1-based index from candidate list>,
      "match_score": <0-100>,
      "reason": "<why this call matches>",
      "suggested_action_type": "<e.g. RIA, IA, CSA>"
    }}
  ]
}}"""

    try:
        raw = llm_fn(sys_prompt, usr_prompt)
        result = json.loads(raw)
        ai_matches = result.get("matches", [])
    except Exception:
        # Fallback: return keyword matches
        return [
            {
                **call,
                "ai_match_score": round(score * 100, 1),
                "ai_match_reason": "Keyword-based match (AI unavailable)",
                "suggested_action_type": call["action_types"][0],
            }
            for call, score in pre_filtered[:top_k]
        ]

    # Build enriched results
    enriched = []
    for m in ai_matches[:top_k]:
        idx = m.get("call_index", 1) - 1
        if 0 <= idx < len(pre_filtered):
            call_data = pre_filtered[idx][0]
            enriched.append({
                **call_data,
                "ai_match_score": m.get("match_score", 0),
                "ai_match_reason": m.get("reason", ""),
                "suggested_action_type": m.get("suggested_action_type", call_data["action_types"][0]),
            })

    return enriched


def build_call_eval_context(call: Dict) -> str:
    """Build evaluation context string from a call dict."""
    parts = [
        f"CALL: {call.get('call_id', 'N/A')}",
        f"TITLE: {call.get('title', 'N/A')}",
        f"DESTINATION: {call.get('destination', 'N/A')}",
        f"ACTION TYPES: {', '.join(call.get('action_types', []))}",
        f"DEADLINE: {call.get('deadline', 'N/A')}",
        f"BUDGET: {call.get('budget_per_project', 'N/A')}",
    ]

    if call.get("expected_outcomes"):
        parts.append(f"\nEXPECTED OUTCOMES:\n{call['expected_outcomes']}")
    if call.get("scope"):
        parts.append(f"\nSCOPE:\n{call['scope']}")

    return "\n".join(parts)


def filter_calls_by_status(status: str = "", db: Optional[List[Dict]] = None) -> List[Dict]:
    """Filter calls by status."""
    if db is None:
        db = HORIZON_CALLS_DB
    if not status:
        return db
    return [c for c in db if c.get("status", "").lower() == status.lower()]


def filter_calls_by_keyword(keyword: str, db: Optional[List[Dict]] = None) -> List[Dict]:
    """Filter calls by keyword in title, scope, or keywords list."""
    if db is None:
        db = HORIZON_CALLS_DB
    if not keyword:
        return db
    kw = keyword.lower()
    results = []
    for c in db:
        searchable = " ".join([
            c.get("title", ""),
            c.get("scope", ""),
            c.get("destination", ""),
            " ".join(c.get("keywords", [])),
        ]).lower()
        if kw in searchable:
            results.append(c)
    return results


def get_call_stats(db: Optional[List[Dict]] = None) -> Dict:
    """Get summary statistics of call database."""
    if db is None:
        db = HORIZON_CALLS_DB
    stats = {
        "total": len(db),
        "open": sum(1 for c in db if c.get("status") == "Open"),
        "forthcoming": sum(1 for c in db if c.get("status") == "Forthcoming"),
        "closed": sum(1 for c in db if c.get("status") == "Closed"),
        "destinations": list(set(c.get("destination", "?") for c in db)),
        "action_types": list(set(
            at for c in db for at in c.get("action_types", [])
        )),
    }
    return stats
