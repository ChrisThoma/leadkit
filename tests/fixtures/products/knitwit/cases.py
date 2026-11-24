"""Test fixture: Knitwit's cases. Made-up titles."""
LEADS = [
    'I keep losing track of my rows, any tips?',
    'Is there a good row counter app for iPhone?',
    'Complete beginner here, how do I read a pattern chart?',
    'Any knitting apps that work on the iPad?',
    'Looking for a crochet counter app that tracks repeats',
]
NOT_LEADS = [
    'Destash: 20 skeins of merino for sale',
    'My finished sweater, first FO of the year!',
    'Yarn on sale, 30% off this weekend',
    'I made a row counter app, would you use it?',
    'Need a new alarm app\nAny good alarm app for Android? My old one stopped working.',
]
TABLET_LEADS = ['Best apps for a new iPad?', 'Which iPad apps are must-haves for crafters?']
TABLET_NOT_LEADS = ['Which case for the iPad mini?', 'iPad battery drains overnight']
LEADS += TABLET_LEADS
NOT_LEADS += TABLET_NOT_LEADS
EXCLUDED = ['knittingmemes', 'YarnSwap', 'craftsnark']
ALLOWED = ['knitting']
