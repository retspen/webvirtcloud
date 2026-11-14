from pathlib import Path

import sass
from django.conf import settings
from django.core.management.base import BaseCommand

from appsettings.views import THEMES_DIR

SCSS = Path(settings.BASE_DIR, "dev", "scss")


def compile_theme(theme):
    return sass.compile(
        string=f"@import '{SCSS}/wvc-themes/{theme}/variables';\n"
        f"@import '{SCSS}/bootstrap-overrides.scss';\n"
        f"@import '{SCSS}/wvc-themes/{theme}/bootswatch';",
        output_style="compressed",
    )


class Command(BaseCommand):
    help = "Compile the themes in dev/scss/wvc-themes into static/css/themes (needs libsass, dev/requirements.txt)."

    def handle(self, *args, **options):
        THEMES_DIR.mkdir(exist_ok=True)
        for theme in sorted(p.name for p in (SCSS / "wvc-themes").iterdir() if p.is_dir()):
            (THEMES_DIR / f"{theme}.min.css").write_text(compile_theme(theme))
