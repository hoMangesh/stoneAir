import io
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

try:
    import pdfplumber
    import requests
    from bs4 import BeautifulSoup
    from duckduckgo_search import DDGS
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except ImportError as exc:
    missing_package = str(exc).split("'")[1] if "'" in str(exc) else str(exc)
    print(f"Missing dependency: {missing_package}")
    print("Install dependencies with:")
    print("  pip install -r requirements.txt")
    print("Or:")
    print("  pip install requests beautifulsoup4 pdfplumber PyMuPDF duckduckgo-search rich")
    sys.exit(1)


console = Console()
BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
REQUEST_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 MachineBrochureAnalyzer/1.0"
DEFAULT_PRODUCT_KG = 100.0
DEFAULT_GRID_EMISSION_FACTOR = 0.40
DEFAULT_LOAD_FACTOR = 0.70
DEFAULT_OPERATING_HOURS = 8000

OFFICIAL_HINTS = {
    "cat": ["cat.com", "caterpillar.com"],
    "caterpillar": ["cat.com", "caterpillar.com"],
    "komatsu": ["komatsu.com"],
    "volvo": ["volvoce.com", "volvo.com"],
    "jcb": ["jcb.com"],
    "hitachi": ["hitachicm.com", "hitachicm.us"],
    "doosan": ["develon-ce.com", "doosanequipment.com"],
    "develon": ["develon-ce.com"],
    "hyundai": ["hd-hyundaice.com", "hyundai-ce.com"],
    "case": ["casece.com"],
    "new holland": ["newholland.com"],
    "bobcat": ["bobcat.com"],
}

THIRD_PARTY_HINTS = [
    "alibaba",
    "amazon",
    "ebay",
    "equipmentworld",
    "lectura-specs",
    "machinerytrader",
    "mascus",
    "ritchiespecs",
    "scribd",
    "slideshare",
    "specguideonline",
    "tradeearthmovers",
    "wikipedia",
]


@dataclass
class SearchResult:
    title: str
    href: str
    body: str = ""


@dataclass
class PowerComponent:
    label: str
    value_kw: float
    source: str


def normalize_machine_name(machine_name: str) -> str:
    return re.sub(r"\s+", " ", machine_name.strip())


def safe_filename(machine_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", machine_name).strip("_") + ".pdf"


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def clean_search_url(url: str) -> str:
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        redirected = parse_qs(parsed.query).get("uddg", [""])[0]
        if redirected:
            return unquote(redirected)
    return url


def expected_domains(machine_name: str) -> List[str]:
    lower_name = machine_name.lower()
    domains: List[str] = []
    for brand, hints in OFFICIAL_HINTS.items():
        if brand in lower_name:
            domains.extend(hints)
    return domains


def is_pdf_url(url: str) -> bool:
    clean_url = url.split("?", 1)[0].lower()
    return clean_url.endswith(".pdf")


def looks_third_party(url: str) -> bool:
    domain = domain_of(url)
    return any(hint in domain for hint in THIRD_PARTY_HINTS)


def is_official_domain(url: str, machine_name: str) -> bool:
    domain = domain_of(url)
    hints = expected_domains(machine_name)
    if hints and any(domain == hint or domain.endswith("." + hint) for hint in hints):
        return True

    first_word = machine_name.lower().split()[0]
    if first_word and first_word in domain and not looks_third_party(url):
        return True

    return False


def score_result(result: SearchResult, machine_name: str) -> int:
    text = f"{result.title} {result.href} {result.body}".lower()
    score = 0

    if is_official_domain(result.href, machine_name):
        score += 80
    if is_pdf_url(result.href):
        score += 50
    if any(word in text for word in ["brochure", "specification", "spec sheet", "catalog", "datasheet"]):
        score += 30
    if machine_name.lower() in text:
        score += 20
    if looks_third_party(result.href):
        score -= 90

    return score


def build_search_queries(machine_name: str) -> List[str]:
    queries = []
    official_domains = expected_domains(machine_name)

    if official_domains:
        for domain in official_domains:
            queries.append(f"site:{domain} {machine_name} brochure PDF")

    queries.extend(
        [
            f"{machine_name} official brochure PDF",
            f"{machine_name} product specification PDF manufacturer",
            f"{machine_name} catalogue PDF official",
        ]
    )
    return queries


def add_result(results: List[SearchResult], seen_urls: set, title: str, href: str, body: str = "") -> None:
    href = clean_search_url(href)
    if not href or href in seen_urls:
        return
    seen_urls.add(href)
    results.append(SearchResult(title=title, href=href, body=body))


def search_with_duckduckgo_package(queries: List[str]) -> Tuple[List[SearchResult], List[str]]:
    results: List[SearchResult] = []
    warnings: List[str] = []
    seen_urls = set()

    try:
        with DDGS() as ddgs:
            for query in queries:
                console.print(f"[cyan]Searching:[/] {query}")
                try:
                    try:
                        items = list(
                            ddgs.text(
                                query,
                                region="wt-wt",
                                safesearch="off",
                                max_results=10,
                            )
                        )
                    except TypeError:
                        items = list(ddgs.text(query, max_results=10))
                    for item in items:
                        add_result(
                            results,
                            seen_urls,
                            item.get("title", ""),
                            item.get("href") or item.get("url", ""),
                            item.get("body", ""),
                        )
                except Exception as exc:
                    warnings.append(f"{query}: {exc}")
                    console.print(f"[yellow]Search warning:[/] {exc}")
    except Exception as exc:
        warnings.append(f"DuckDuckGo client failed: {exc}")

    return results, warnings


def search_with_duckduckgo_html(queries: List[str]) -> Tuple[List[SearchResult], List[str]]:
    results: List[SearchResult] = []
    warnings: List[str] = []
    seen_urls = set()

    headers = {"User-Agent": USER_AGENT}
    for query in queries:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        console.print(f"[cyan]Fallback search:[/] {query}")
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for result in soup.select(".result"):
                link = result.select_one("a.result__a")
                snippet = result.select_one(".result__snippet")
                if not link:
                    continue
                href = link.get("href", "")
                add_result(
                    results,
                    seen_urls,
                    link.get_text(" ", strip=True),
                    href,
                    snippet.get_text(" ", strip=True) if snippet else "",
                )
        except Exception as exc:
            warnings.append(f"{query}: {exc}")
            console.print(f"[yellow]Fallback search warning:[/] {exc}")

    return results, warnings


def search_machine(machine_name: str) -> Tuple[List[SearchResult], List[str]]:
    queries = build_search_queries(machine_name)

    results, warnings = search_with_duckduckgo_package(queries)
    if not results:
        fallback_results, fallback_warnings = search_with_duckduckgo_html(queries)
        results.extend(fallback_results)
        warnings.extend(fallback_warnings)

    results.sort(key=lambda result: score_result(result, machine_name), reverse=True)
    return results, warnings


def find_pdf_links(page_url: str) -> List[str]:
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    links: List[str] = []

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        text = tag.get_text(" ", strip=True).lower()
        absolute_url = urljoin(page_url, href)
        combined = f"{absolute_url} {text}".lower()
        if ".pdf" in combined and any(
            word in combined for word in ["brochure", "spec", "catalog", "datasheet", "pdf"]
        ):
            links.append(absolute_url)

    return links


def find_brochure_url(machine_name: str, results: List[SearchResult]) -> Optional[str]:
    console.print("[cyan]Finding brochure...[/]")

    direct_pdfs = [result.href for result in results if is_pdf_url(result.href)]
    direct_pdfs.sort(
        key=lambda url: (
            0 if is_official_domain(url, machine_name) else 1,
            1 if looks_third_party(url) else 0,
        )
    )
    if direct_pdfs:
        return direct_pdfs[0]

    candidate_links: List[SearchResult] = []
    for result in results[:10]:
        if looks_third_party(result.href) and not is_official_domain(result.href, machine_name):
            continue
        try:
            for pdf_url in find_pdf_links(result.href):
                candidate_links.append(SearchResult(result.title, pdf_url, result.body))
        except Exception as exc:
            console.print(f"[yellow]Could not inspect page:[/] {result.href} ({exc})")

    if not candidate_links:
        return None

    candidate_links.sort(key=lambda item: score_result(item, machine_name), reverse=True)
    return candidate_links[0].href


def download_pdf(url: str, machine_name: str, save_file: bool = True) -> Tuple[bytes, Optional[Path]]:
    console.print("[cyan]Downloading brochure...[/]")

    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" not in content_type and not response.content[:5] == b"%PDF-":
        raise ValueError("The brochure URL did not return a PDF file.")

    if not save_file:
        return response.content, None

    DOWNLOAD_DIR.mkdir(exist_ok=True)
    file_path = DOWNLOAD_DIR / safe_filename(machine_name)
    file_path.write_bytes(response.content)
    return response.content, file_path


def extract_pdf_text(pdf_bytes: bytes) -> str:
    console.print("[cyan]Extracting text...[/]")

    text_parts: List[str] = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_parts.append(page_text)
    except Exception as exc:
        console.print(f"[yellow]pdfplumber warning:[/] {exc}")

    text = "\n".join(text_parts).strip()
    if text:
        return text

    try:
        import fitz

        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            for page in document:
                page_text = page.get_text("text") or ""
                if page_text.strip():
                    text_parts.append(page_text)
    except ImportError:
        console.print("[yellow]PyMuPDF is not installed; skipped secondary PDF extraction fallback.[/]")
    except Exception as exc:
        console.print(f"[yellow]PyMuPDF warning:[/] {exc}")

    return "\n".join(text_parts).strip()


def nearby_lines(text: str, keywords: List[str], max_lines: int = 4) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    matches: List[str] = []

    for index, line in enumerate(lines):
        lower_line = line.lower()
        if any(keyword.lower() in lower_line for keyword in keywords):
            start = max(0, index - 1)
            end = min(len(lines), index + max_lines)
            block = " ".join(lines[start:end])
            if block not in matches:
                matches.append(block)

    return " | ".join(matches[:4]) or "Not Specified"


def extract_value(text: str, patterns: List[str]) -> str:
    normalized = re.sub(r"[ \t]+", " ", text)
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" :;-")
    return "Not Specified"


def parse_number(value: str) -> float:
    return float(value.replace(",", ""))


def dedupe_numbers(values: List[float]) -> List[float]:
    deduped: List[float] = []
    for value in values:
        if not any(abs(value - existing) < 0.001 for existing in deduped):
            deduped.append(value)
    return deduped


def context_label(line: str) -> str:
    lower_line = line.lower()
    if "main" in lower_line and "motor" in lower_line:
        return "main_motor"
    if "draft" in lower_line:
        return "drafting_motor"
    if "ring" in lower_line and "rail" in lower_line:
        return "ring_rail_drive"
    if "suction" in lower_line:
        return "suction"
    if "robo" in lower_line or "robot" in lower_line:
        return "optional_robot"
    if "spindle" in lower_line:
        return "spindle_drive"
    if "motor" in lower_line:
        return "motor"
    return "power_component"


def representative_range_value(low: float, high: float, label: str) -> float:
    if high <= low:
        return high

    # For ring spinning brochures, the common 55-110 kW main motor range is an
    # options range. Use a representative high-capacity motor, not both values.
    if label == "main_motor" and low <= 90 <= high:
        return 90.0

    # For other option ranges, choose a high representative configuration.
    return low + (high - low) * 0.64


def find_power_components_kw(text: str) -> List[PowerComponent]:
    components: List[PowerComponent] = []
    seen_sources = set()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    range_pattern = r"(\d[\d,]*(?:\.\d+)?)\s*(?:-|–|to)\s*(\d[\d,]*(?:\.\d+)?)\s*kW\b"
    single_kw_pattern = r"(?<![-–])\b(\d[\d,]*(?:\.\d+)?)\s*kW\b"
    hp_pattern = r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:hp|HP)\b"

    for line in lines:
        label = context_label(line)
        range_spans = []

        for match in re.finditer(range_pattern, line, flags=re.IGNORECASE):
            low = parse_number(match.group(1))
            high = parse_number(match.group(2))
            if 0 < low <= high <= 10000:
                value = representative_range_value(low, high, label)
                source = f"{line} -> representative {value:.2f} kW"
                if source not in seen_sources:
                    components.append(PowerComponent(label, value, source))
                    seen_sources.add(source)
                range_spans.append(match.span())

        for match in re.finditer(single_kw_pattern, line, flags=re.IGNORECASE):
            if any(start <= match.start() < end for start, end in range_spans):
                continue
            value = parse_number(match.group(1))
            if 0 < value <= 10000:
                source = f"{line} -> {value:.2f} kW"
                if source not in seen_sources:
                    components.append(PowerComponent(label, value, source))
                    seen_sources.add(source)

        for match in re.finditer(hp_pattern, line, flags=re.IGNORECASE):
            value = parse_number(match.group(1)) * 0.7457
            if 0 < value <= 10000:
                source = f"{line} -> {value:.2f} kW from hp"
                if source not in seen_sources:
                    components.append(PowerComponent(label, value, source))
                    seen_sources.add(source)

    return components


def select_power_components(components: List[PowerComponent]) -> List[PowerComponent]:
    selected: List[PowerComponent] = []
    used_labels = set()

    priority_labels = [
        "main_motor",
        "drafting_motor",
        "ring_rail_drive",
        "suction",
        "optional_robot",
        "spindle_drive",
    ]

    for label in priority_labels:
        matches = [component for component in components if component.label == label]
        if matches:
            selected.append(max(matches, key=lambda component: component.value_kw))
            used_labels.add(label)

    generic_matches = [
        component
        for component in components
        if component.label not in used_labels and component.label in {"motor", "power_component"}
    ]
    if not selected and generic_matches:
        selected.append(max(generic_matches, key=lambda component: component.value_kw))

    return selected


def find_production_values(text: str) -> Dict[str, float]:
    production: Dict[str, float] = {}

    patterns = {
        "kg_per_year": [
            (r"(\d[\d,]*(?:\.\d+)?)\s*(?:tonnes?|tons?|t)\s*/?\s*(?:year|yr|annum)", 1000.0),
            (r"(\d[\d,]*(?:\.\d+)?)\s*(?:tonnes?|tons?|t)\s+(?:of\s+)?[A-Za-z ]{0,40}?\s*(?:per|/)\s*(?:machine-)?(?:year|yr|annum)", 1000.0),
            (r"(\d[\d,]*(?:\.\d+)?)\s*kg\s*/?\s*(?:year|yr|annum)", 1.0),
            (r"(\d[\d,]*(?:\.\d+)?)\s*kg\s+(?:of\s+)?[A-Za-z ]{0,40}?\s*(?:per|/)\s*(?:machine-)?(?:year|yr|annum)", 1.0),
        ],
        "kg_per_day": [
            (r"(\d[\d,]*(?:\.\d+)?)\s*(?:tonnes?|tons?|t)\s*/?\s*day", 1000.0),
            (r"(\d[\d,]*(?:\.\d+)?)\s*kg\s*/?\s*day", 1.0),
        ],
        "kg_per_hour": [
            (r"(\d[\d,]*(?:\.\d+)?)\s*(?:tonnes?|tons?|t)\s*/?\s*(?:hour|hr|h)", 1000.0),
            (r"(\d[\d,]*(?:\.\d+)?)\s*kg\s*/?\s*(?:hour|hr|h)", 1.0),
        ],
        "kg_per_minute": [
            (r"(\d[\d,]*(?:\.\d+)?)\s*kg\s*/?\s*(?:minute|min)", 1.0),
        ],
    }

    for unit_key, unit_patterns in patterns.items():
        values: List[float] = []
        for pattern, multiplier in unit_patterns:
            values.extend(
                parse_number(value) * multiplier
                for value in re.findall(pattern, text, flags=re.IGNORECASE)
            )
        if values:
            production[unit_key] = max(values)

    return production


def production_to_kg_per_hour(production: Dict[str, float], operating_hours: int) -> Optional[float]:
    if "kg_per_year" in production:
        return production["kg_per_year"] / operating_hours
    if "kg_per_day" in production:
        return production["kg_per_day"] / 24
    if "kg_per_hour" in production:
        return production["kg_per_hour"]
    if "kg_per_minute" in production:
        return production["kg_per_minute"] * 60
    return None


def source_guidance_for_missing_inputs(
    has_power: bool,
    has_production: bool,
    uses_default_load_factor: bool = True,
    uses_default_operating_hours: bool = True,
    uses_default_emission_factor: bool = True,
) -> Dict[str, str]:
    guidance = {
        "calculation_readiness": "Ready" if has_power and has_production else "Incomplete",
        "installed_power_kw_source": "Found in brochure." if has_power else (
            "Missing. Use OEM technical data sheet, electrical specification sheet, "
            "motor list, machine nameplate, electrical panel rating, or supplier quotation."
        ),
        "production_rate_source": "Found in brochure." if has_production else (
            "Missing. Use OEM production table, process guarantee sheet, spinning plan, "
            "ERP/MES production records, shift logbook, or measured kg output per shift."
        ),
        "load_factor_source": (
            "Default assumption 0.70 used. Replace with metered machine power, VFD/PLC logs, "
            "energy meter readings, or plant engineering estimate for the operating recipe."
            if uses_default_load_factor else "User supplied."
        ),
        "operating_hours_source": (
            "Default assumption 8000 hr/year used. Replace with annual running hours from "
            "machine logs, maintenance records, production calendar, or OEE records."
            if uses_default_operating_hours else "User supplied."
        ),
        "grid_emission_factor_source": (
            "Default assumption 0.40 kg CO2e/kWh used. Replace with supplier-specific electricity factor, "
            "national grid factor, CEA India CO2 baseline, EPA eGRID, IEA factor, or an Ecoinvent/GaBi dataset."
            if uses_default_emission_factor else "User supplied."
        ),
    }

    if has_power and has_production:
        guidance["next_action"] = "Review assumptions, then store values in the machine/process knowledge graph."
    else:
        guidance["next_action"] = (
            "Do not finalize carbon results. Collect the missing inputs from the listed primary sources, "
            "then rerun the calculation."
        )

    return guidance


def calculate_energy_and_emissions(
    text: str,
    product_kg: float = DEFAULT_PRODUCT_KG,
    emission_factor: float = DEFAULT_GRID_EMISSION_FACTOR,
    load_factor: float = DEFAULT_LOAD_FACTOR,
    operating_hours: int = DEFAULT_OPERATING_HOURS,
) -> Dict[str, str]:
    power_components = find_power_components_kw(text)
    selected_components = select_power_components(power_components)
    production = find_production_values(text)
    production_rate = production_to_kg_per_hour(production, operating_hours)
    has_power = bool(selected_components)
    has_production = production_rate is not None and production_rate > 0

    result = {
        "product_quantity_kg": f"{product_kg:.2f} kg",
        "emission_factor": f"{emission_factor:.2f} kg CO2e/kWh",
        "load_factor": f"{load_factor:.2f}",
        "operating_hours": f"{operating_hours} hr/year",
        "installed_power_kw": "Not Specified",
        "average_power_kw": "Not Specified",
        "production_rate_kg_hr": "Not Specified",
        "energy_per_kg_kwh": "Not Specified",
        "total_energy_kwh": "Not Specified",
        "emissions_kg_co2e": "Not Specified",
        "low_carbon_0_10": "Not Specified",
        "typical_grid_0_37": "Not Specified",
        "global_grid_0_40": "Not Specified",
        "carbon_intensive_0_70": "Not Specified",
        "uncertainty_energy_kwh": "Not Specified",
        "uncertainty_emissions_kg_co2e": "Not Specified",
        "data_quality": "Incomplete - missing brochure inputs.",
        "calculation_status": "Power and production values were not found in the brochure.",
    }

    if has_power:
        installed_power = sum(component.value_kw for component in selected_components)
        average_power = installed_power * load_factor
        result["installed_power_kw"] = f"{installed_power:.2f} kW"
        result["average_power_kw"] = f"{average_power:.2f} kW"
        result["selected_power_components"] = " + ".join(
            f"{component.label} {component.value_kw:.2f} kW" for component in selected_components
        )
        result["all_power_values_found"] = " | ".join(component.source for component in power_components[:12])
    else:
        installed_power = None
        average_power = None

    if has_production:
        result["production_rate_kg_hr"] = f"{production_rate:.2f} kg/hr"
        for key, value in production.items():
            label = key.replace("_", " ")
            result[label] = f"{value:.2f}"

    if average_power is None and production_rate is None:
        return result
    if average_power is None:
        result["calculation_status"] = "Production was found, but power values were not found."
        return result
    if production_rate is None or production_rate <= 0:
        result["calculation_status"] = "Power was found, but production values were not found."
        return result

    energy_per_kg = average_power / production_rate
    total_energy = energy_per_kg * product_kg
    emissions = total_energy * emission_factor
    low_energy = total_energy * 0.66
    high_energy = total_energy * 1.33
    low_emissions = low_energy * emission_factor
    high_emissions = high_energy * emission_factor

    result.update(
        {
            "energy_per_kg_kwh": f"{energy_per_kg:.4f} kWh/kg",
            "total_energy_kwh": f"{total_energy:.2f} kWh",
            "emissions_kg_co2e": f"{emissions:.2f} kg CO2e",
            "low_carbon_0_10": f"{total_energy * 0.10:.2f} kg CO2e",
            "typical_grid_0_37": f"{total_energy * 0.37:.2f} kg CO2e",
            "global_grid_0_40": f"{total_energy * 0.40:.2f} kg CO2e",
            "carbon_intensive_0_70": f"{total_energy * 0.70:.2f} kg CO2e",
            "uncertainty_energy_kwh": f"{low_energy:.2f}-{high_energy:.2f} kWh for {product_kg:.2f} kg",
            "uncertainty_emissions_kg_co2e": f"{low_emissions:.2f}-{high_emissions:.2f} kg CO2e at {emission_factor:.2f} kg CO2e/kWh",
            "data_quality": "Calculated - brochure inputs found; defaults used for load, hours, and grid factor.",
            "calculation_status": "Calculated from extracted brochure values.",
        }
    )
    return result


def extract_efficiency(text: str) -> Dict[str, str]:
    fuel_patterns = [
        r"fuel consumption\s*[:\-]?\s*([^\n\r|]{1,80})",
        r"consumes?\s+([0-9.]+\s*(?:l/h|l/hr|litres/hour|gal/hr)[^\n\r|]{0,40})",
        r"([0-9.]+\s*(?:l/h|l/hr|litres/hour|gal/hr))",
    ]
    productivity_patterns = [
        r"productivity\s*[:\-]?\s*([^\n\r|]{1,80})",
        r"output\s*[:\-]?\s*([^\n\r|]{1,80})",
    ]

    return {
        "fuel_consumption": extract_value(text, fuel_patterns),
        "productivity": extract_value(text, productivity_patterns),
        "operating_efficiency": nearby_lines(
            text,
            ["efficiency", "fuel efficiency", "operating efficiency", "performance", "productivity"],
        ),
    }


def extract_consumables(text: str) -> Dict[str, str]:
    return {
        "fuel": extract_value(text, [r"\b(diesel|petrol|gasoline|electric|cng|lng)\b"]),
        "engine_oil": extract_value(text, [r"engine oil\s*[:\-]?\s*([^\n\r|]{1,80})", r"\b(SAE\s*[0-9A-Z-]+W?[0-9A-Z-]*)\b"]),
        "hydraulic_oil": extract_value(text, [r"hydraulic oil\s*[:\-]?\s*([^\n\r|]{1,80})", r"\b(ISO\s*VG\s*[0-9]+)\b"]),
        "coolant": extract_value(text, [r"coolant\s*[:\-]?\s*([^\n\r|]{1,80})"]),
        "filters": nearby_lines(text, ["filter", "filters"]),
        "remarks": nearby_lines(text, ["fuel", "hydraulic oil", "engine oil", "coolant", "grease", "DEF", "lubricants"]),
    }


def extract_emissions(text: str) -> Dict[str, str]:
    standard = extract_value(
        text,
        [
            r"\b(Tier\s*[0-9]\s*(?:Final)?)\b",
            r"\b(Stage\s*(?:V|IV|III|II|I|[0-9]+))\b",
            r"\b(BS\s*(?:VI|IV|III|[0-9]+))\b",
            r"emission standards?\s*[:\-]?\s*([^\n\r|]{1,80})",
        ],
    )

    return {
        "standard": standard,
        "co2": extract_value(text, [r"\bCO2\b\s*[:\-]?\s*([^\n\r|]{1,80})", r"\bCO₂\b\s*[:\-]?\s*([^\n\r|]{1,80})"]),
        "nox": extract_value(text, [r"\bNOx\b\s*[:\-]?\s*([^\n\r|]{1,80})"]),
        "remarks": nearby_lines(text, ["emission", "emissions", "Stage V", "Tier 4", "BS VI", "CO2", "NOx", "particulate"]),
    }


def extract_with_llm(text: str) -> Optional[Dict[str, Dict[str, str]]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        prompt = f"""
Extract machine brochure information as strict JSON with this shape:
{{
  "efficiency": {{
    "fuel_consumption": "...",
    "productivity": "...",
    "operating_efficiency": "..."
  }},
  "consumables": {{
    "fuel": "...",
    "engine_oil": "...",
    "hydraulic_oil": "...",
    "coolant": "...",
    "filters": "..."
  }},
  "emissions": {{
    "standard": "...",
    "co2": "...",
    "nox": "...",
    "remarks": "..."
  }}
}}

Use "Not Specified" when the brochure does not clearly state a value.

Brochure text:
{text[:18000]}
"""
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            input=prompt,
        )
        raw_text = response.output_text.strip()
        raw_text = re.sub(r"^```(?:json)?|```$", "", raw_text, flags=re.IGNORECASE | re.MULTILINE).strip()
        parsed = json.loads(raw_text)
        if all(section in parsed for section in ["efficiency", "consumables", "emissions"]):
            return parsed
    except Exception as exc:
        console.print(f"[yellow]LLM fallback warning:[/] {exc}")

    return None


def summarize_missing_values(text: str, data: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    extraction_sections = ["efficiency", "consumables", "emissions"]
    if any(
        value != "Not Specified"
        for section in extraction_sections
        for value in data[section].values()
    ):
        return data

    llm_data = extract_with_llm(text)
    if llm_data:
        for section in ["carbon_calculation", "data_sources"]:
            if section in data:
                llm_data[section] = data[section]
        return llm_data

    console.print("[yellow]Exact keywords were limited; using brochure context summary fallback.[/]")
    summary = nearby_lines(
        text,
        [
            "engine",
            "fuel",
            "hydraulic",
            "performance",
            "emission",
            "standard",
            "operating",
            "service refill",
        ],
        max_lines=6,
    )

    data["efficiency"]["operating_efficiency"] = summary
    data["consumables"]["remarks"] = summary
    data["emissions"]["remarks"] = summary
    return data


def analyze_brochure(text: str) -> Dict[str, Dict[str, str]]:
    console.print("[cyan]Analyzing brochure...[/]")

    carbon_calculation = calculate_energy_and_emissions(text)
    has_power = carbon_calculation.get("installed_power_kw") != "Not Specified"
    has_production = carbon_calculation.get("production_rate_kg_hr") != "Not Specified"

    data = {
        "efficiency": extract_efficiency(text),
        "consumables": extract_consumables(text),
        "emissions": extract_emissions(text),
        "carbon_calculation": carbon_calculation,
        "data_sources": source_guidance_for_missing_inputs(has_power, has_production),
    }
    return summarize_missing_values(text, data)


def display_results(machine_name: str, brochure_url: str, data: Dict[str, Dict[str, str]], saved_path: Optional[Path]) -> None:
    console.print("\n" + "=" * 34)
    console.print(f"Machine : {machine_name}")
    console.print("=" * 34)
    console.print(f"Brochure URL : {brochure_url}")
    if saved_path:
        console.print(f"Saved PDF : {saved_path}")

    sections = [
        ("EFFICIENCY", data["efficiency"]),
        ("CONSUMABLES", data["consumables"]),
        ("EMISSIONS", data["emissions"]),
        ("CARBON CALCULATION - 100 KG PRODUCT", data["carbon_calculation"]),
        ("MISSING DATA AND SOURCE GUIDANCE", data["data_sources"]),
    ]

    for section_name, values in sections:
        table = Table(title=section_name, show_header=False, box=None)
        table.add_column("Field", style="bold")
        table.add_column("Value")
        for key, value in values.items():
            label = key.replace("_", " ").title()
            table.add_row(label, value or "Not Specified")
        console.print(table)


def choose_option() -> str:
    console.print("\nChoose Option:\n")
    console.print("1. Download Brochure + Display Data")
    console.print("2. Display Data Only\n")

    choice = input("Enter Choice: ").strip()
    if choice not in {"1", "2"}:
        raise ValueError("Invalid choice. Please enter 1 or 2.")
    return choice


def main() -> None:
    console.print(Panel.fit("Machine Brochure Scraper & Analyzer", style="bold green"))

    machine_name = normalize_machine_name(input("Enter Machine Model: "))
    if not machine_name:
        console.print("[red]Machine model is required.[/]")
        return

    try:
        choice = choose_option()
        console.print("\n[cyan]Searching official website...[/]")
        results, search_warnings = search_machine(machine_name)
        if not results:
            console.print("[red]No search results found.[/]")
            console.print(
                "[yellow]This usually means the search provider blocked the request, "
                "internet access is unavailable, or the PDF is not indexed.[/]"
            )
            if search_warnings:
                console.print("[yellow]Search diagnostics:[/]")
                for warning in search_warnings[-5:]:
                    console.print(f"- {warning}")
            console.print(
                "[yellow]Try:[/] include the manufacturer name, check internet access, "
                "or search the brochure URL manually on the official manufacturer site."
            )
            return

        brochure_url = find_brochure_url(machine_name, results)
        if not brochure_url:
            console.print("[red]No official PDF brochure found.[/]")
            console.print("[yellow]Tip:[/] Try including the manufacturer name, for example 'CAT 320D' or 'Volvo EC210'.")
            return

        pdf_bytes, saved_path = download_pdf(brochure_url, machine_name, save_file=(choice == "1"))
        text = extract_pdf_text(pdf_bytes)
        if not text:
            console.print("[red]The PDF was downloaded, but no extractable text was found.[/]")
            console.print("[yellow]This may be a scanned brochure. OCR can be added in a future version.[/]")
            return

        data = analyze_brochure(text)
        console.print("[green]Done.[/]")
        display_results(machine_name, brochure_url, data, saved_path)

    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/]")
    except Exception as exc:
        console.print(f"[red]Error:[/] {exc}")


if __name__ == "__main__":
    main()
