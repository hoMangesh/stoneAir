We are building a Manufacturing Intelligence Engine.

Not a traditional ESG calculator.

The platform reconstructs:
- provenance
- manufacturing routes
- machines
- consumables
- energy
- emissions

from minimal user input.

Primary industry:
- Apparel
- Footwear

Primary output:
- Product Carbon Footprint
- Water Footprint
- Process Breakdown
- Confidence Score

## Active Engineering Priority

Before starting new feature work, complete the generic carbon-engine/domain-pack
dispatch. The core engine must delegate domain-specific carbon calculation to a
registered domain pack through the `CarbonModel.evaluate(...)` contract, rather
than reading apparel model attributes directly. Preserve existing apparel
outputs and tests while establishing the extension point for a future Footwear
domain pack.

Immediate next task:
- Implement and verify the generic carbon-engine/domain-pack response path.
