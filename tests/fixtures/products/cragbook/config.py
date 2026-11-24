"""Test fixture: Cragbook, a made-up climbing logbook. Not a real product."""
import re
NAME = 'Cragbook'
from pathlib import Path as _Path
REPO = str(_Path(__file__).parent / 'repo')
LEADS_DIR = 'leads'
STALE_DAYS = 4
USER_AGENT = 'cragbook-watch/0.1 (by u/example)'
PAUSE = 30.0
SUBREDDITS = ['climbing', 'bouldering', 'climbharder', 'ClimbingGym', 'climbingcirclejerk', 'tradclimbing', 'IndoorClimbing', 'ClimbingPorn', 'sportclimbing', 'Rockclimbing']
COMMENT_PHRASES = ['"climbing log"', '"logbook"', '"track my sends"']
RULES_UNCHECKED = {'sportclimbing', 'Rockclimbing', 'iosapps', 'androidapps', 'apps'}
SEARCHES = ['logbook OR "climbing log"', 'app OR apps', '"training plan" OR "how to train" OR plateau', '"where to start" OR beginner OR "first time"']
GROUPS = [{'name': 'apps', 'subreddits': ['iosapps', 'androidapps', 'apps'], 'searches': ['climbing OR bouldering']}]
SIGNALS = {
    '\\b(climbing|bouldering|route) (log|logbook|journal|tracker|diary)\\b': 5,
    '\\btrack(ing)? (my )?(sends|climbs|progress|sessions?)\\b': 5,
    '\\b(plateau(ed)?|stuck at v\\d+|not (improving|progressing))\\b': 4,
    '\\b(training|workout) (plan|routine|schedule)s?\\b': 4,
    '\\bwhere (do i|to|should i) (even )?(start|begin)\\b|\\b(complete|absolute|total) beginner\\b|\\bnew to (climbing|bouldering)\\b': 3,
    '\\b(any|good|best|free) (apps?|tools?)\\b|\\bapp (recommendation|suggestion)s?\\b|\\bwhich app\\b': 3,
    '\\bgrades?\\b': 1,
}
NEGATIVE = {
    '\\bfor sale\\b|\\bwts\\b|\\bwtb\\b': -10,
    '\\b(shoes?|harness|rope|chalk) (review|size|sizing)\\b|\\bresol(e|ing)\\b': -6,
    "\\bpromo(tion)?\\b|\\bmy (app|tool|site|website)\\b|\\bi('?m| am| have|'ve)? (just |finally )?(made|built|building|wrote|created|released|launched|developing) an? (\\w+ ){0,3}(app|tool|site|website|game)\\b|\\bwould you use\\b": -8,
}
MIN_SCORE = 5
NEW_FEEDS = SUBREDDITS[:4] + ['tradclimbing']
SCORE_TABLES = [(None, SIGNALS), (None, NEGATIVE)]
(TOP, RECENT) = ('', '&filter=recent')
THREADS_SEARCHES = {
    'communities': [('climbingthreads', TOP, True, '10000000000000001'), ('climbingthreads', RECENT, True, '10000000000000001'), ('boulderingthreads', TOP, True)],
    'keywords': [('climbing log', RECENT, False), ('bouldering progress', TOP, False), ('climbing app', TOP, False)],
    'topics': [('climbing training plan', TOP, False), ('new to bouldering', TOP, False)],
}
APP_LEADS = False
POST_SUBS = {
    'ShowYourApp': {'flair': 'Launch', 'rules': 'Say you made it, link plus one question.'},
    'iosapps': {'flair': 'Paid', 'every_days': 30, 'per_account': True, 'rules': 'Once a month per developer. Say you made it.'},
}
THREADS_MEDIA = {'video': 'docs/preview/cragbook-preview.mp4', 'cover': 'docs/preview/cover.jpg'}
THREADS_KEYWORDS = ['bouldering', 'climbing', 'climbing gym', 'sport climbing', 'trad climbing', 'climbing training', 'send', 'project']
THREADS_TAGS = ['Climbing Threads', 'Bouldering Threads']
THREADS_EXTRA = {
    '\\?': 1,
    '\\bbeginner\\b|\\bjust start(ed|ing)\\b|\\bnew to (climbing|bouldering)\\b': 1,
    '\\btips?\\b|\\badvice\\b|\\brecommend': 1,
    '\\b(what|which|any|best) (\\w+ ){0,3}(exercises?|drills?)\\b|\\bget(ting)? better at\\b': 3,
    '\\bhow (do|did|should|can) (i|you)\\b': 1,
}
THREADS_MIN_SCORE = 4
# The column the drafts page shows as "where" for a Threads row.
THREADS_WHERE = 'discipline'


def threads_row(row, text):
    """Cragbook's Threads file has a discipline column: bouldering, or rope."""
    t = text.lower()
    row['discipline'] = 'bouldering' if re.search('\\bboulder', t) else 'rope'
    return row


APP_STORE_ID = 1000000002
ASO_KEYWORDS = ['climbing log', 'bouldering', 'climbing tracker', 'route log', 'climbing journal', 'boulder grades', 'climbing training', 'send tracker', 'gym climbing', 'hangboard']
ASO_COUNTRIES = ['de', 'fr', 'au']
ASO_LISTING_FILE = 'docs/app-store/fields.py'
ASO_LISTING_DIR = 'docs/app-store/locales'
ASO_ABOUT = 'Cragbook is a made-up paid iPhone and iPad app (iOS and Android) for logging climbs: routes and boulders sent, grades, sessions, and progress over time.'
ASO_AVOID = {'game': 'climbing games', 'map': 'crag maps or guidebooks (the app has none)', 'gear': 'climbing gear shops'}
ASO_COMPETITORS = {'Example Crag': 1000000201, 'Sample Sends': 1000000202}
ASO_TOPIC = ['climb', 'boulder', 'rock', 'route', 'grade', 'log', 'journal', 'diary', 'wall', 'crag', 'rope', 'send', 'track', 'progress']
# Words always fine in a keyword field, whatever Wiktionary says.
ASO_REVIEW_KEEP = ['hangboard', 'quiz']
