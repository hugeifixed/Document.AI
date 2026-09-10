"""Task-oriented admin navigation built from Django's permitted model links."""

from django.contrib import admin
from django.urls import reverse

PLATFORM_GROUPS = (
    (
        "workspace",
        "Workspace",
        "Organize projects, datasets, and uploaded documents.",
        (
            ("project", "Projects", "folder_open"),
            ("dataset", "Datasets", "folder_copy"),
            ("document", "Documents", "description"),
        ),
    ),
    (
        "workflows",
        "Workflows & rules",
        "Define document types and how documents are processed.",
        (
            ("categorydefinition", "Document types", "category"),
            ("workflowconfiguration", "Workflows", "account_tree"),
            ("extractiontemplate", "Extraction templates", "file_copy"),
            ("reviewpolicy", "Review rules", "rule"),
        ),
    ),
    (
        "processing",
        "Processing & results",
        "Track processing runs and inspect their output.",
        (
            ("run", "Processing runs", "play_circle"),
            ("segment", "Document segments", "splitscreen"),
            ("classificationresult", "Classification results", "label"),
            ("extractedfield", "Extracted fields", "data_object"),
        ),
    ),
    (
        "quality",
        "Review & quality",
        "Review corrections, measure accuracy, and trace changes.",
        (
            ("groundtruthlabel", "Ground-truth labels", "fact_check"),
            ("reviewaction", "Review history", "rate_review"),
            ("evaluation", "Evaluations", "analytics"),
            ("auditevent", "Audit log", "history"),
        ),
    ),
    (
        "ai",
        "AI configuration",
        "Configure extraction schemas, prompts, and model settings.",
        (
            ("schemaversion", "Extraction schemas", "schema"),
            ("promptversion", "Prompt versions", "chat"),
            ("modelconfiguration", "Model settings", "tune"),
        ),
    ),
    (
        "technical",
        "Technical records",
        "Debug document tasks, artifacts, and source locations.",
        (
            ("runitem", "Document tasks", "checklist"),
            ("processingartifact", "Processing artifacts", "inventory_2"),
            ("sourceunit", "Pages & worksheets", "auto_stories"),
            ("sourcespan", "Source locations", "location_searching"),
        ),
    ),
)


def group_platform_apps(app_list):
    """Preserve permission-filtered URLs and Add actions from the admin registry."""
    platform = next((app for app in app_list if app["app_label"] == "docai"), None)
    result = {
        "groups": [],
        "app_url": platform["app_url"] if platform else "",
        "other_apps": [app for app in app_list if app["app_label"] != "docai"],
    }
    if not platform:
        return result

    remaining = {model["model"]._meta.model_name: model for model in platform["models"]}
    for key, title, description, entries in PLATFORM_GROUPS:
        items = []
        for model_name, label, icon in entries:
            model = remaining.pop(model_name, None)
            if model:
                items.append({**model, "name": label, "icon": icon})
        if items:
            result["groups"].append(
                {"key": key, "title": title, "description": description, "items": items}
            )

    # Newly registered models remain discoverable until assigned to a group.
    if remaining:
        result["groups"].append(
            {
                "key": "other",
                "title": "Other platform records",
                "description": "Additional platform records.",
                "items": [{**model, "icon": "table_rows"} for model in remaining.values()],
            }
        )
    return result


def sidebar_navigation(request):
    grouped = group_platform_apps(admin.site.get_app_list(request))
    navigation = []
    for group in grouped["groups"]:
        items = []
        for model in group["items"]:
            link = model["admin_url"] or model["add_url"]
            if link:
                title = model["name"] if model["admin_url"] else f"Add {model['name']}"
                items.append({"title": title, "icon": model["icon"], "link": link})
        if items:
            navigation.append(
                {"title": group["title"], "items": items, "expanded": group["key"] == "workspace"}
            )
    if navigation:
        navigation[0].update(app_title="Document AI Platform", app_url=grouped["app_url"])

    tools = {
        "auth": ("Users & access", None),
        "dj_cache_panel": ("Cache tools", "dj_cache_panel:index"),
        "dj_control_room_base": ("Control room", "dj_control_room_base:index"),
    }
    administration = []
    for app in grouped["other_apps"]:
        title, panel_url = tools.get(app["app_label"], (app["name"], None))
        items = []
        for model in app["models"]:
            link = model["admin_url"] or model["add_url"]
            if link:
                items.append(
                    {
                        "title": model["name"],
                        "icon": "settings",
                        "link": reverse(panel_url) if panel_url else link,
                    }
                )
        if items:
            administration.append({"title": title, "items": items})
    if administration:
        administration[0]["app_title"] = "Administration"
    return navigation + administration
