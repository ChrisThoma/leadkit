"""Test fixture: Mossling, a made-up terrarium widget. Not a real product."""
NAME = 'Mossling'
from pathlib import Path as _Path
REPO = str(_Path(__file__).parent / 'repo')
LEADS_DIR = 'leads'
STALE_DAYS = 4
USER_AGENT = 'mossling-watch/0.1 (by u/example)'
PAUSE = 35.0
FOLD_SUBS = ['GalaxyFold', 'foldables', 'androidapps']
SUBREDDITS = ['iosapps', 'iphone', 'ipad', 'iOSsetups', 'terrariums', 'moss', 'CozyGamers']
RULES_UNCHECKED = set(SUBREDDITS) | {'ipadapps'} | set(FOLD_SUBS)
EXCLUDED = {'widgy', 'apphookup'}
NEW_FEEDS = ['iOSsetups']
SEARCHES = ['"terrarium app" OR "moss widget" OR "plant widget"', '"calming app" OR "relaxing app" OR "cozy app"', '"virtual pet" OR "digital pet"']
import types


def _tablet():
    SUBREDDITS = ['ipad', 'ipadapps', 'iosapps']
    SEARCHES = ['apps OR app']
    SITE_SEARCHES = ['"ipad" widget apps']
    GATE = '\\b(ipad|tablet)\\b'
    SIGNALS = {
        '\\b(which|what|any|best|favou?rite|good|must[- ]have|recommend\\w*)\\b (\\S+ ){0,4}(apps?|widgets?)\\b': 3,
        '\\bapps? to try\\b|\\bhidden gems?\\b': 3,
        '\\bapps?\\b[^.!\\n]*\\?': 2,
        '\\b(case|keyboard|pencil|screen protector|battery)\\b': -4,
    }
    GROUP = {'name': 'tablet', 'subreddits': SUBREDDITS, 'searches': SEARCHES, 'site_searches': SITE_SEARCHES}
    (TOP, RECENT) = ('', '&filter=recent')
    THREADS = [('ipad widgets', TOP, False), ('best ipad apps', TOP, False)]
    return types.SimpleNamespace(**{k: v for k, v in locals().items()})


tablet = _tablet()
FOLD_GATE = '\\b(z ?fold ?\\d*|galaxy fold|foldables?|cover (screen|display))\\b'
FOLD_SIGNALS = {
    '\\b(which|what|any|best|favou?rite|good|cool|fun)\\b (\\S+ ){0,4}(apps?|widgets?)\\b': 3,
    '\\b(cover|outer) (screen|display)\\b.{0,30}\\b(apps?|widgets?)\\b': 3,
    '\\bapps?\\b[^.!\\n]*\\?': 2,
    '\\b(crease|hinge|screen protector|cases?|warranty|repair)\\b': -4,
}
FOLD_GROUP = {'name': 'fold', 'subreddits': FOLD_SUBS, 'searches': ['apps OR app OR widget']}
GROUPS = [tablet.GROUP, FOLD_GROUP]
POST_SUBS = {
    'ShowYourApp': {'flair': 'Launch', 'rules': 'Say you made it, link plus one question.'},
    'iosapps': {'flair': 'Paid', 'every_days': 30, 'per_account': True, 'not_before': '2026-12-10', 'rules': 'Once a month per developer. Say you made it.'},
    'ipadapps': {'flair': 'Showcase', 'rules': 'iPad apps only, say you made it.'},
}
SIGNALS = {
    '\\b(terrarium|moss|plant)\\b.{0,30}\\b(app|widget)s?\\b|\\b(app|widget)s?\\b.{0,30}\\b(terrarium|moss)\\b': 5,
    '\\b(calm(ing)?|relax(ing)?|cozy|zen|peaceful)\\b.{0,20}\\b(apps?|widgets?)\\b': 4,
    '\\bsomething (calm(ing)?|relaxing|peaceful) to (look at|watch)\\b': 3,
    '\\b(virtual|digital) pets?\\b.{0,30}\\b(apps?|iphone|ipad|phone)\\b': 4,
    '\\b(any|good|best|favou?rite|recommend\\w*|looking for) (\\w+ ){0,3}(apps?|widgets?)\\b|\\bis there an? (\\w+ ){0,2}app\\b': 3,
    '\\?': 1,
}
NEGATIVE = {
    '\\b(mold|mould|rot|pests?|gnats?|overwater\\w*|humidity)\\b': -5,
    '\\bfor sale\\b|\\bselling\\b|\\bwts\\b': -6,
    '\\b(meditation|guided|sleep sounds?|white noise)\\b': -3,
    "\\bpromo(tion)?\\b|\\bmy (new )?(app|game|widget|site)\\b|\\bi('?m| am| have|'ve)? (just |finally )?(made|built|building|created|released|launched) an? (\\w+ ){0,3}(app|tool|site|widget|game)\\b|\\bwould you use\\b": -8,
}
MIN_SCORE = 5
SCORE_TABLES = [(None, SIGNALS), (None, NEGATIVE), (tablet.GATE, tablet.SIGNALS), (FOLD_GATE, FOLD_SIGNALS)]
(TOP, RECENT) = ('', '&filter=recent')
THREADS_SEARCHES = {
    'keywords': [('mossling', RECENT, False), ('terrarium app', TOP, False), ('calming app iphone', TOP, False)],
    'topics': [('something calming to look at', TOP, False), ('cozy apps iphone', TOP, False)],
    'tablet': tablet.THREADS,
}
THREADS_MEDIA = {'video': 'docs/preview/mossling-preview.mp4'}
APP_STORE_ID = 1000000003
ASO_KEYWORDS = ['terrarium', 'moss', 'moss widget', 'plant widget', 'calm widget', 'cozy', 'relaxing', 'zen garden', 'virtual pet', 'widget']
ASO_LISTING_FILE = 'docs/app-store/fields.py'
ASO_LISTING_DIR = 'docs/app-store/locales'
ASO_PLAY_METADATA_DIR = 'android/fastlane/metadata/android'
ASO_ABOUT = 'Mossling is a made-up paid iPhone and iPad app: a tiny moss terrarium that grows on your Home Screen as a widget. Not a game.'
ASO_AVOID = {'game': 'plant games (Mossling has no goals)', 'care': 'real plant care apps', 'sleep': 'sleep sounds apps'}
ASO_TOPIC = ['moss', 'terrarium', 'plant', 'garden', 'widget', 'calm', 'relax', 'cozy', 'zen', 'green']
