"""Common function words, dropped from fulltext queries.

The fulltext index keeps every word (its analyzer can hold one language's
stop words only), so without this a French query matches every French
document on "de" and "et". Lower case; covers the plan's query languages.
"""

STOPWORDS = frozenset(
    # English
    "a an and are as at be but by for from has have in into is it its of on or that the their this to was "
    "were what which who with "
    # French
    "au aux avec ce ces dans de des du elle en est et il ils la le les leur leurs ou par pas pour qu que qui "
    "sa se ses son sont sur un une "
    # German
    "auf aus bei das dem den der des die ein eine einer eines im ist mit nicht oder sich und von zu zum zur "
    # Spanish
    "al como con del el ella es las los para por se su sus una y "
    # Italian
    "agli ai alla alle che col dei degli della delle di gli il nei nel nella per sono tra uno "
    # Portuguese
    "as da das do dos em na nas no nos os ou pela pelo um uma "
    # Dutch
    "het een en van op te dat zijn voor met niet aan ook als bij door om".split()
)
