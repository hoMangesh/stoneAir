from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
MASTER_DATA_ROOT = DATA_ROOT / "masters"
CALCULATION_DATA_ROOT = DATA_ROOT / "calculations"
INFERENCE_DATA_ROOT = DATA_ROOT / "inference"
INFERENCE_RECORDS_CSV = INFERENCE_DATA_ROOT / "inference_records.csv"

PRODUCT_TAXONOMY_CSV = DATA_ROOT / "products" / "Product_Taxonomy_V1.csv"
PRODUCT_TEMPLATE_CSV = DATA_ROOT / "templates" / "Product_Template_Library_V1.csv"
ROUTE_LIBRARY_CSV = DATA_ROOT / "routes" / "Route_Library_V2.csv"

MASTER_DATASETS = {
    "products": MASTER_DATA_ROOT / "products.csv",
    "materials": MASTER_DATA_ROOT / "materials.csv",
    "material_origins": MASTER_DATA_ROOT / "material_origins.csv",
    "manufacturing_routes": MASTER_DATA_ROOT / "manufacturing_routes.csv",
    "route_processes": MASTER_DATA_ROOT / "route_processes.csv",
    "processes": MASTER_DATA_ROOT / "processes.csv",
    "process_steps": MASTER_DATA_ROOT / "process_steps.csv",
    "machine_categories": MASTER_DATA_ROOT / "machine_categories.csv",
    "machine_models": MASTER_DATA_ROOT / "machine_models.csv",
    "machine_brochures": MASTER_DATA_ROOT / "machine_brochures.csv",
    "machine_spec_extractions": MASTER_DATA_ROOT / "machine_spec_extractions.csv",
    "machine_energy_profiles": MASTER_DATA_ROOT / "machine_energy_profiles.csv",
    "machine_recommender_bridge": MASTER_DATA_ROOT / "machine_recommender_models_bridge.csv",
    "consumables": MASTER_DATA_ROOT / "consumables.csv",
    "chemicals": MASTER_DATA_ROOT / "chemicals.csv",
    "suppliers": MASTER_DATA_ROOT / "suppliers.csv",
    "factories": MASTER_DATA_ROOT / "factories.csv",
    "factory_machine_map": MASTER_DATA_ROOT / "factory_machine_map.csv",
    "countries": MASTER_DATA_ROOT / "countries.csv",
    "transport_modes": MASTER_DATA_ROOT / "transport_modes.csv",
    "transport_routes": MASTER_DATA_ROOT / "transport_routes.csv",
    "yield_models": MASTER_DATA_ROOT / "yield_models.csv",
    "emission_factors": MASTER_DATA_ROOT / "emission_factors.csv",
}
