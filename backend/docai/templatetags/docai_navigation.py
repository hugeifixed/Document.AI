from django import template

from docai.navigation import group_platform_apps

register = template.Library()
register.simple_tag(group_platform_apps, name="group_platform_apps")
