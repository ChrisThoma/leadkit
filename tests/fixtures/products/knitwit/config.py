"""Test fixture: Knitwit, a made-up row counter for knitters. Not a real product."""
NAME = 'Knitwit'
from pathlib import Path as _Path
REPO = str(_Path(__file__).parent / 'repo')
LEADS_DIR = 'marketing/leads'
STALE_DAYS = 3
USER_AGENT = 'knitwit-watch/0.1 (by u/example)'
PAUSE = 35.0
SUBREDDITS = ['knitting', 'crochet', 'YarnAddicts', 'knittinghelp', 'Brochet', 'Sock_Knitting', 'ipad', 'androidapps', 'iosapps']
EXCLUDED = {'knittingmemes', 'yarnswap', 'craftsnark'}
NEW_FEEDS = ['knittinghelp', 'Sock_Knitting']
SEARCHES = ['knitting OR crochet OR "row counter"', 'pattern OR chart OR stitch', 'app OR apps']
SITE_SEARCHES = ['"row counter app" OR "knitting app" OR "crochet app"', '"knitting counter" OR "stitch counter"']
TABLET_SUBREDDITS = ['ipad', 'iosapps']
TABLET_SEARCHES = ['apps OR app']
TABLET_SITE_SEARCHES = ['"ipad" knitting apps']
CRAFT = '(knit\\w*|crochet\\w*|yarn|stitch\\w*|purl)'
DEVICE = '(iphone|ipad|phone|android|tablet|mobile)'
SIGNALS = {
    f'\\b(keep|keeping|lose|losing|lost) (track|count) of (my )?(rows?|rounds?|stitch(es)?|repeats?)\\b': 5,
    '\\brow counters?\\b|\\bstitch counters?\\b': 4,
    f'\\b{CRAFT} (apps?|counter|tracker)\\b': 4,
    f'\\b(apps?|software) (for|to help with) {CRAFT}\\b': 4,
    '\\b(complete|absolute|total) beginner\\b|\\bnew to (knitting|crochet)\\b|\\bwhere (do i|to|should i) (even )?(start|begin)\\b': 2,
    '\\b(pattern|chart) (reading|help)\\b|\\bhow (do|can) i read (a |this )?(pattern|chart)\\b': 3,
    '\\b(knitting|crochet) (on|with) (my |an? |the )?(iphone|ipad|phone|tablet)\\b': 3,
}
CRAFT_WORDS = '\\b(knit\\w*|crochet\\w*|yarn|stitch\\w*|patterns?|rows?|rounds?)\\b'
CRAFT_SIGNALS = {
    f'\\b(on|for) (my |an? |the )?{DEVICE}\\b|\\bios\\b': 2,
    '\\b(which|what|any|good|best|free|simple|easy|recommend\\w*) (\\w+ ){0,2}(apps?|tools?)\\b|\\blooking for (an? |some )?(\\w+ ){0,3}(apps?|tool)\\b': 3,
}
TABLET = '\\b(ipad|tablet)\\b'
TABLET_SIGNALS = {
    '\\b(which|what|any|best|favou?rite|good|must[- ]have|recommend\\w*)\\b (\\S+ ){0,4}apps?\\b': 3,
    '\\bapps? to try\\b|\\bhidden gems?\\b': 3,
    '\\bapps?\\b[^.!\\n]*\\?': 2,
    '\\b(case|keyboard|pencil|screen protector|battery)\\b': -4,
}
NEGATIVE = {
    '\\bfor sale\\b|\\bdestash\\b|\\bwts\\b|\\bswap\\b': -10,
    '\\b(my|this) (finished|latest) (sweater|scarf|hat|sock|blanket)s?\\b|\\bfo\\b|\\bfinished object\\b': -6,
    '\\b\\d+% off\\b|\\bon sale\\b|\\bdiscount\\b|\\bcoupon\\b': -6,
    "\\bpromo(tion)?\\b|\\bmy (app|tool|site|website)\\b|\\bi('?m| am| have|'ve)? (made|built|building|wrote|created|released|developing) an? (\\w+ ){0,3}(app|tool|site|website)\\b|\\bwould you use\\b": -8,
}
MIN_SCORE = 5
SCORE_TABLES = [(None, SIGNALS), (CRAFT_WORDS, CRAFT_SIGNALS), (None, NEGATIVE), (TABLET, TABLET_SIGNALS)]
GROUPS = [{'name': 'tablet', 'subreddits': TABLET_SUBREDDITS, 'searches': TABLET_SEARCHES, 'site_searches': TABLET_SITE_SEARCHES}]
POST_SUBS = {
    'ShowYourApp': {'flair': 'Launch', 'rules': 'Say you made it, link plus one question.'},
    'iosapps': {'flair': 'Paid', 'every_days': 30, 'per_account': True, 'rules': 'Once a month per developer. Say you made it.'},
    'knitting': {'thread': 'weekly app thread', 'rules': 'No self-promotion outside the weekly thread.'},
}
(TOP, RECENT) = ('', '&filter=recent')
THREADS_SEARCHES = {
    'tablet': [('ipad apps', TOP, False), ('best ipad apps', TOP, False)],
    'core': [('knitting', TOP, False), ('row counter', TOP, False), ('crochet app', TOP, False), ('knitting app', RECENT, True)],
}
THREADS_MEDIA = {'video': 'AppStore/preview/knitwit-preview.mp4', 'cover': 'AppStore/cover.jpg'}
APP_STORE_ID = 1000000001
ASO_KEYWORDS = ['row counter', 'knitting', 'knitting counter', 'crochet', 'crochet counter', 'stitch counter', 'knitting app', 'pattern tracker', 'yarn', 'knit']
ASO_COUNTRIES = ['de', 'jp', 'fr']
ASO_LISTING_FILE = 'AppStore/fields.py'
ASO_LISTING_DIR = 'AppStore/listing'
ASO_PLAY_METADATA_DIR = 'android/fastlane/metadata/android'
ASO_ABOUT = 'Knitwit is a made-up paid iPhone and iPad app (iOS and Android) that counts rows and repeats for knitting and crochet patterns.'
ASO_AVOID = {'game': 'knitting games', 'shop': 'yarn shops', 'ai': 'AI pattern generators (the app has none)'}
ASO_COMPETITORS = {'Example Counter': 1000000101, 'Sample Stitch': 1000000102}
ASO_TOPIC = ['knit', 'crochet', 'yarn', 'stitch', 'row', 'pattern', 'count', 'wool', 'needle']
