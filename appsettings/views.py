from pathlib import Path

from admin.decorators import superuser_only
from django.conf import settings
from django.contrib import messages
from django.db import DatabaseError, transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.utils.translation import gettext_noop as _
from logs.audit import audit
from operations.utils import BOUNDS

from appsettings.models import AppSettings


# the themes "manage.py build_themes" compiles; base.html links the chosen one
THEMES_DIR = Path(settings.BASE_DIR, "static", "css", "themes")

# the whole-number settings and their range: they are read as numbers, and a
# letter would break the page or the job that reads one
NUMBERS = {
    **{key: bounds[:2] for key, bounds in BOUNDS.items()},
    "LOGS_PER_PAGE": (1, 1000),
    "LOGIN_FAILURE_LIMIT": (1, 1000),
    "LOGIN_LOCKOUT_MINUTES": (1, 10080),
    "SNAPSHOT_FREE_SPACE_PERCENT": (0, 100),
    "SNAPSHOT_FREE_SPACE_MIN_GIB": (0, 100000),
    "INSTANCE_VOLUME_DEFAULT_OWNER_UID": (0, 4294967294),
    "INSTANCE_VOLUME_DEFAULT_OWNER_GID": (0, 4294967294),
}


# the Settings page's groups, in order; a setting in none shows under Other
GROUPS = [
    (_("New VM defaults"), ["INSTANCE_ARCH_DEFAULT_TYPE", "INSTANCE_MACHINE_DEFAULT_TYPE",
                            "INSTANCE_FIRMWARE_DEFAULT_TYPE", "INSTANCE_CPU_DEFAULT_MODE", "INSTANCE_NIC_DEFAULT_TYPE",
                            "INSTANCE_VIDEO_DEFAULT_TYPE", "INSTANCE_INPUT_DEFAULT_DEVICE", "INSTANCE_CDROM_ADD"]),
    (_("Disks"), ["INSTANCE_VOLUME_DEFAULT_BUS", "INSTANCE_VOLUME_DEFAULT_FORMAT", "INSTANCE_VOLUME_DEFAULT_CACHE",
                  "INSTANCE_VOLUME_DEFAULT_IO", "INSTANCE_VOLUME_DEFAULT_DISCARD",
                  "INSTANCE_VOLUME_DEFAULT_DETECT_ZEROES", "INSTANCE_VOLUME_DEFAULT_SCSI_CONTROLLER",
                  "INSTANCE_VOLUME_DEFAULT_OWNER_UID", "INSTANCE_VOLUME_DEFAULT_OWNER_GID"]),
    (_("Clones"), ["CLONE_INSTANCE_AUTO_NAME", "CLONE_INSTANCE_DEFAULT_PREFIX"]),
    (_("Console"), ["CONSOLE_SCALE", "CONSOLE_VIEW_ONLY", "CONSOLE_RESIZE_SESSION", "CONSOLE_CLIP_VIEWPORT"]),
    (_("VM access and owners"), ["SHOW_ACCESS_ROOT_PASSWORD", "SHOW_ACCESS_SSH_KEYS",
                                 "ALLOW_INSTANCE_MULTIPLE_OWNER", "QUOTA_DEBUG"]),
    (_("Snapshots and jobs"), ["SNAPSHOT_FREE_SPACE_PERCENT", "SNAPSHOT_FREE_SPACE_MIN_GIB",
                               "WORKER_CONCURRENCY", "JOB_RETENTION_DAYS"]),
    (_("Login"), ["LOGIN_FAILURE_LIMIT", "LOGIN_LOCKOUT_MINUTES"]),
    (_("Lists and pages"), ["VIEW_INSTANCES_LIST_STYLE", "VM_DRBD_STATUS", "LOGS_PER_PAGE"]),
]


def refusal(setting, value):
    """Why the value cannot be saved for the setting, or None."""
    if len(value) > AppSettings._meta.get_field("value").max_length:
        return _("%(setting)s takes at most %(length)s characters") % {
            "setting": setting.name, "length": AppSettings._meta.get_field("value").max_length}
    if setting.key in NUMBERS:
        low, high = NUMBERS[setting.key]
        if not (value.isascii() and value.isdigit() and len(value) <= 10 and low <= int(value) <= high):
            return _("%(setting)s must be a whole number between %(low)s and %(high)s") % {
                "setting": setting.name, "low": low, "high": high}
    elif setting.choices and value not in setting.choices_as_list():
        return _("%(setting)s must be one of %(choices)s") % {
            "setting": setting.name, "choices": ", ".join(setting.choices_as_list())}
    return None


@superuser_only
def appsettings(request):
    """The settings, in groups; a group's form saves its changed settings,
    or none of them when one is refused."""
    bootstrap_theme = AppSettings.objects.get(key="BOOTSTRAP_THEME")
    themes_list = sorted(p.name.removesuffix(".min.css") for p in THEMES_DIR.glob("*.min.css"))
    # the theme has its own form
    settings_by_key = {s.key: s for s in AppSettings.objects.exclude(key="BOOTSTRAP_THEME")}

    if request.method == "POST":
        if "BOOTSTRAP_THEME" in request.POST:
            theme = request.POST.get("BOOTSTRAP_THEME", "")
            if theme not in themes_list:
                messages.error(request, _("Unknown theme: %(theme)s") % {"theme": theme})
                return HttpResponseRedirect(request.get_full_path())
            if theme != bootstrap_theme.value:
                with audit(request, None, "Setting Theme", f"change to {theme}"):
                    bootstrap_theme.value = theme
                    bootstrap_theme.save()
            msg = _("Theme is changed. Now: %(theme)s") % {"theme": theme}
            messages.success(request, msg)
            return HttpResponseRedirect(request.get_full_path())

        # a field counts as changed against the value the page showed (was-KEY): one left
        # as it was does not undo what another administrator saved meanwhile
        posted = sorted(((s, request.POST[s.key]) for s in settings_by_key.values() if s.key in request.POST),
                        key=lambda item: item[0].name)
        changed = [(s, value) for s, value in posted if value != request.POST.get(f"was-{s.key}", s.value)]
        refusals = [refused for refused in (refusal(s, value) for s, value in changed) if refused]
        for refused in refusals:
            messages.error(request, refused)
        if changed and not refusals:
            action = "change " + ", ".join(f"{s.name} to {value}" for s, value in changed)
            try:
                # one row, and all of the group or none of it
                with audit(request, None, "Settings", action), transaction.atomic():
                    for setting, value in changed:
                        setting.value = value
                        setting.save()
            except DatabaseError as err:  # the audit row records it as failed
                messages.error(request, err)
            else:
                messages.success(request, _("Saved: %(settings)s") % {"settings": ", ".join(s.name for s, _v in changed)})
        elif not refusals:
            messages.info(request, _("Nothing changed"))
        return HttpResponseRedirect(request.get_full_path())

    groups = []
    for title, keys in GROUPS:
        groups.append((title, [settings_by_key.pop(key) for key in keys if key in settings_by_key]))
    if settings_by_key:
        groups.append((_("Other"), sorted(settings_by_key.values(), key=lambda s: s.name)))
    for _title, settings_list in groups:
        for setting in settings_list:
            setting.bounds = NUMBERS.get(setting.key)
    return render(request, "appsettings.html",
                  {"bootstrap_theme": bootstrap_theme, "themes_list": themes_list, "groups": groups})
