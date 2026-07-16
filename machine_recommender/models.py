from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class Machine:
    """Represents a manufacturing machine with its specifications."""

    id: str
    name: str
    category: str
    description: str
    purpose: str
    automation: Literal["Manual", "Semi Automatic", "Fully Automatic"]
    applications: list[str]


@dataclass
class ManufacturingProcess:
    """Represents a step in the manufacturing workflow."""

    id: str
    name: str
    description: str
    sequence: int
    optional: bool
    machines: list[Machine]


@dataclass
class InferredProduct:
    """Product attributes inferred from the product name."""

    raw_name: str
    material_id: Optional[str]
    product_type_id: str
    product_type_name: str
    category: str
    gender: Optional[str]
    detected_features: list[str]
    fabric_structure_determined: str


@dataclass
class WorkflowResult:
    """Complete workflow recommendation result for a product."""

    industry: str
    product_name: str
    category: str
    product_type: str
    material: str
    fabric_structure: str
    features: list[str]
    workflow: list[ManufacturingProcess]
