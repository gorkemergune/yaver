"""Meta (Instagram / Facebook) ad reports for Metrics: a skeleton. The Marketing API call is
not written yet, so the integration is always pending; what it waits for is said
precisely (no credentials vs. credentials but no code)."""

from dataclasses import dataclass

from app.config import Settings

NO_CREDENTIALS = (
    "Meta reklam hesabı bağlı değil (META_ACCESS_TOKEN ve META_AD_ACCOUNT_ID bekleniyor)."
)
NOT_BUILT = "Meta reklam anahtarları var ama entegrasyon henüz yazılmadı (O3 iskeleti)."


@dataclass(frozen=True, slots=True)
class AdsStatus:
    connected: bool
    note: str


def ads_status(settings: Settings) -> AdsStatus:
    if not (settings.meta_access_token and settings.meta_ad_account_id):
        return AdsStatus(False, NO_CREDENTIALS)
    return AdsStatus(False, NOT_BUILT)
