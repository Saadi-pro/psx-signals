# Stocks the scanner looks at. Edit freely: add/remove tickers (PSX symbols).
# Only liquid stocks are worth day trading, so keep this list to actively traded names.
WATCHLIST = [
    "OGDC","PPL","POL","MARI","PSO","HUBC","ENGRO","FFC","EFERT","LUCK","MLCF","DGKC","FCCL","CHCC",
    "MEBL","HBL","UBL","MCB","BAHL","NBP","SYS","TRG","NETSOL","AVN","PAEL","TELE","KEL","SNGP","SSGC",
    "ATRL","NRL","PRL","KOHC","FATIMA","EPCL","LOTCHEM","ILP","INDU","HCAR","MTL","ISL","PIOC","CNERGY",
    "WTL","HASCOL","TPLP","AGP","GATM","THALL","DCR","FLYNG","BOP","AKBL","FABL","ABOT","SEARL","HGFA",
]
# Approximate Shariah-compliant list (KMI-30 style). It changes every 6 months:
# VERIFY against the latest KMI list from PSX / Meezan before relying on the tag.
KMI = {
    "OGDC","PPL","POL","MARI","PSO","HUBC","ENGRO","FFC","EFERT","LUCK","MLCF","DGKC","FCCL","CHCC",
    "MEBL","SYS","ATRL","NRL","KOHC","FATIMA","EPCL","LOTCHEM","ILP","INDU","HCAR","MTL","ISL","PIOC",
}
