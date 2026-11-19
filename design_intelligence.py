"""
PyForge Vision AI - Advanced Design Intelligence
Version: 2.0
Purpose: Structured design analysis, preservation and
targeted-edit reasoning for screenshot-to-application work.

This module provides knowledge and prompts. It does not
perform visual inference without a connected AI provider.
"""

from datetime import datetime, timezone

DESIGN_INTELLIGENCE_VERSION = "2.0"

DESIGN_ANALYSIS_FRAMEWORK = {
    "structure": [
        "Identify the overall page boundaries and layout.",
        "Identify header, footer, sidebars and navigation.",
        "Identify main content regions and their relationships.",
        "Estimate alignment, spacing and relative proportions.",
        "Identify repeated sections and component groupings."
    ],
    "visual_hierarchy": [
        "Identify the most visually prominent elements.",
        "Determine heading, subheading and body-text hierarchy.",
        "Observe size, weight, contrast and alignment.",
        "Identify primary and secondary actions.",
        "Preserve the original reading and scanning order."
    ],
    "colour_and_surface": [
        "Observe dominant, secondary and accent colours.",
        "Identify background and surface colour relationships.",
        "Observe borders, shadows, gradients and transparency.",
        "Record contrast relationships without inventing exact values.",
        "Preserve the original visual atmosphere."
    ],
    "typography": [
        "Identify apparent font families where possible.",
        "Observe font size, weight, line height and letter spacing.",
        "Identify heading and paragraph styles.",
        "Do not claim exact font identification from an unclear image."
    ],
    "components": [
        "Identify buttons, cards, panels and containers.",
        "Identify input fields, selectors and form controls.",
        "Identify icons, badges, tabs and menus.",
        "Record component position, size and visual state.",
        "Infer interactions cautiously and label uncertain behaviour."
    ],
    "responsive_design": [
        "Identify evidence of desktop, tablet or mobile layout.",
        "Do not assume unseen responsive layouts.",
        "Preserve the reference at its supplied viewport first.",
        "Plan responsive behaviour without changing the reference design.",
        "Report assumptions that require user confirmation."
    ],
    "functionality": [
        "Identify visible interactive controls.",
        "Map each control to an intended action.",
        "Identify navigation destinations where visible.",
        "Do not invent backend behaviour.",
        "Test implemented interactions before declaring completion."
    ]
}

DESIGN_LOCK_RULES = [
    "The original uploaded image is immutable.",
    "Never replace or modify the original reference file.",
    "Only change elements explicitly requested by the user.",
    "Preserve all unrelated layout and styling.",
    "Do not introduce new sections or controls without permission.",
    "Do not simplify or redesign the reference autonomously.",
    "Ask for clarification before ambiguous or destructive changes.",
    "Keep every revision separate from the original reference.",
    "Compare the result against the reference after each revision.",
    "Report differences honestly."
]

TARGETED_EDIT_PROTOCOL = [
    "Identify the exact element named by the user.",
    "Locate that element in the reconstructed interface.",
    "Determine the smallest safe change that satisfies the request.",
    "List neighbouring elements that must remain unchanged.",
    "Apply the change only to the intended element.",
    "Check layout and interactions for unintended side effects.",
    "Compare before and after versions.",
    "Report exactly what changed and what was preserved."
]

FIDELITY_DIMENSIONS = {
    "layout": "Page structure, positioning and proportions",
    "spacing": "Margins, padding, gaps and alignment",
    "colour": "Backgrounds, surfaces, accents and contrast",
    "typography": "Font appearance, hierarchy and line spacing",
    "components": "Shape, size, borders and component appearance",
    "navigation": "Menu structure, location and visual treatment",
    "responsive": "Behaviour at the requested viewport",
    "content": "Visible text, labels and content placement"
}

ANALYSIS_OUTPUT_SCHEMA = {
    "reference_id": "string",
    "project_name": "string",
    "viewport": {
        "width": "number or unknown",
        "height": "number or unknown"
    },
    "sections": [],
    "components": [],
    "design_tokens": {},
    "layout_observations": [],
    "interaction_observations": [],
    "responsive_observations": [],
    "uncertainties": [],
    "preservation_requirements": [],
    "analysis_status": "pending"
}


def get_design_knowledge(domain=None):
    """Return all design knowledge or one requested domain."""
    if domain is None:
        return {
            "framework": DESIGN_ANALYSIS_FRAMEWORK,
            "design_lock": DESIGN_LOCK_RULES,
            "targeted_edit_protocol": TARGETED_EDIT_PROTOCOL,
            "fidelity_dimensions": FIDELITY_DIMENSIONS
        }

    if domain == "design_lock":
        return DESIGN_LOCK_RULES

    if domain == "targeted_edit":
        return TARGETED_EDIT_PROTOCOL

    if domain == "fidelity":
        return FIDELITY_DIMENSIONS

    return DESIGN_ANALYSIS_FRAMEWORK.get(domain)


def build_design_analysis_prompt(project_name, reference_id):
    """Build instructions for a future vision model."""
    return f"""
PYFORGE ADVANCED DESIGN ANALYSIS

PROJECT: {project_name}
REFERENCE ID: {reference_id}
KNOWLEDGE VERSION: {DESIGN_INTELLIGENCE_VERSION}

ROLE
Act as a senior UI/UX designer, visual analyst and
frontend reconstruction engineer.

OBJECTIVE
Analyse the supplied reference image and produce a
structured description for faithful application reconstruction.

MANDATORY RULES
{chr(10).join('- ' + item for item in DESIGN_LOCK_RULES)}

ANALYSIS REQUIREMENTS
{chr(10).join('- ' + item for group in DESIGN_ANALYSIS_FRAMEWORK.values() for item in group)}

OUTPUT
Return structured observations covering:
1. Overall layout and page regions.
2. Navigation and component inventory.
3. Typography and visual hierarchy.
4. Colour and surface observations.
5. Spacing and alignment.
6. Visible interactions.
7. Responsive evidence.
8. Uncertainties and confidence limitations.
9. Elements that must remain unchanged.

Do not invent pixel measurements, fonts, colours or
behaviour that cannot be reliably observed.

Do not generate or modify the application yet.
Analysis must be completed and reviewed first.
""".strip()


def build_targeted_edit_prompt(
    instruction,
    project_name,
    reference_id,
    affected_element=None
):
    """Build a narrowly scoped edit instruction."""
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("A non-empty user instruction is required.")

    target = affected_element or "Identify only the element explicitly named by the user."

    return f"""
PYFORGE TARGETED DESIGN EDIT

PROJECT: {project_name}
REFERENCE ID: {reference_id}

USER INSTRUCTION:
{instruction.strip()}

TARGET:
{target}

EDIT RULES:
{chr(10).join('- ' + item for item in TARGETED_EDIT_PROTOCOL)}

PROTECTED RULES:
{chr(10).join('- ' + item for item in DESIGN_LOCK_RULES)}

Do not make unrelated improvements.
Do not redesign other elements.
If the target is unclear, ask before editing.
Return a change report listing modified and preserved elements.
""".strip()


def score_analysis_completeness(observations):
    """
    Score whether an analysis record covers expected categories.
    This is a completeness check, NOT an image-fidelity score.
    """
    if not isinstance(observations, dict):
        raise TypeError("Observations must be a dictionary.")

    categories = [
        "sections",
        "components",
        "design_tokens",
        "layout_observations",
        "interaction_observations",
        "responsive_observations",
        "uncertainties"
    ]

    completed = []
    missing = []

    for category in categories:
        value = observations.get(category)
        if isinstance(value, (list, dict)) and value:
            completed.append(category)
        else:
            missing.append(category)

    score = round((len(completed) / len(categories)) * 100)

    return {
        "completeness_score": score,
        "completed_categories": completed,
        "missing_categories": missing,
        "score_type": "analysis_completeness_not_visual_accuracy",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def get_design_intelligence_status():
    return {
        "component": "PyForge Advanced Design Intelligence",
        "version": DESIGN_INTELLIGENCE_VERSION,
        "status": "loaded",
        "analysis_frameworks": list(DESIGN_ANALYSIS_FRAMEWORK),
        "design_lock": "enabled",
        "targeted_edit_protocol": "enabled",
        "fidelity_dimensions": list(FIDELITY_DIMENSIONS),
        "vision_model_connected": False,
        "actual_image_analysis": "requires_external_vision_model"
    }
