/* A searchable universe of 9,800 US listings.

   The first block is real: these symbols and names are public facts, so a
   listing row is accurate even though every NUMBER attached to it here is
   fabricated. The remainder is generated to reach the corpus-scale count, and
   is flagged `synthetic` so the interface can say which rows are invented. */

const REAL = `AAPL|Apple Inc.|NASDAQ
MSFT|Microsoft Corporation|NASDAQ
NVDA|NVIDIA Corporation|NASDAQ
AMZN|Amazon.com, Inc.|NASDAQ
GOOGL|Alphabet Inc.|NASDAQ
META|Meta Platforms, Inc.|NASDAQ
BRK.B|Berkshire Hathaway Inc.|NYSE
LLY|Eli Lilly and Company|NYSE
AVGO|Broadcom Inc.|NASDAQ
JPM|JPMorgan Chase & Co.|NYSE
TSLA|Tesla, Inc.|NASDAQ
UNH|UnitedHealth Group Incorporated|NYSE
XOM|Exxon Mobil Corporation|NYSE
V|Visa Inc.|NYSE
PG|The Procter & Gamble Company|NYSE
MA|Mastercard Incorporated|NYSE
JNJ|Johnson & Johnson|NYSE
COST|Costco Wholesale Corporation|NASDAQ
HD|The Home Depot, Inc.|NYSE
MRK|Merck & Co., Inc.|NYSE
ABBV|AbbVie Inc.|NYSE
CVX|Chevron Corporation|NYSE
PEP|PepsiCo, Inc.|NASDAQ
KO|The Coca-Cola Company|NYSE
ADBE|Adobe Inc.|NASDAQ
WMT|Walmart Inc.|NYSE
CRM|Salesforce, Inc.|NYSE
BAC|Bank of America Corporation|NYSE
MCD|McDonald's Corporation|NYSE
ACN|Accenture plc|NYSE
NFLX|Netflix, Inc.|NASDAQ
LIN|Linde plc|NASDAQ
AMD|Advanced Micro Devices, Inc.|NASDAQ
TMO|Thermo Fisher Scientific Inc.|NYSE
CSCO|Cisco Systems, Inc.|NASDAQ
ABT|Abbott Laboratories|NYSE
ORCL|Oracle Corporation|NYSE
DIS|The Walt Disney Company|NYSE
INTC|Intel Corporation|NASDAQ
QCOM|QUALCOMM Incorporated|NASDAQ
VZ|Verizon Communications Inc.|NYSE
INTU|Intuit Inc.|NASDAQ
TXN|Texas Instruments Incorporated|NASDAQ
CAT|Caterpillar Inc.|NYSE
IBM|International Business Machines Corporation|NYSE
NKE|NIKE, Inc.|NYSE
GE|General Electric Company|NYSE
NOC|Northrop Grumman Corporation|NYSE
BXP|BXP, Inc.|NYSE
FCX|Freeport-McMoRan Inc.|NYSE
PRU|Prudential Financial, Inc.|NYSE
CP|Canadian Pacific Kansas City Limited|NYSE
CHD|Church & Dwight Co., Inc.|NYSE
ACGL|Arch Capital Group Ltd.|NASDAQ
ALLY|Ally Financial Inc.|NYSE
WH|Wyndham Hotels & Resorts, Inc.|NYSE
JAZZ|Jazz Pharmaceuticals plc|NASDAQ
ATI|ATI Inc.|NYSE
STZ|Constellation Brands, Inc.|NYSE
DAR|Darling Ingredients Inc.|NYSE
ELV|Elevance Health, Inc.|NYSE
LVS|Las Vegas Sands Corp.|NYSE
WAL|Western Alliance Bancorporation|NYSE
CELH|Celsius Holdings, Inc.|NASDAQ
IONQ|IonQ, Inc.|NYSE
CORZ|Core Scientific, Inc.|NASDAQ
TROW|T. Rowe Price Group, Inc.|NASDAQ
TTWO|Take-Two Interactive Software, Inc.|NASDAQ
LAD|Lithia Motors, Inc.|NYSE
FTAI|FTAI Aviation Ltd.|NASDAQ
ZTS|Zoetis Inc.|NYSE
ZM|Zoom Communications Inc.|NASDAQ
YUMC|Yum China Holdings, Inc.|NYSE
WY|Weyerhaeuser Company|NYSE
WULF|TeraWulf Inc.|NASDAQ
MELI|MercadoLibre, Inc.|NASDAQ
MKTX|MarketAxess Holdings Inc.|NASDAQ
LW|Lamb Weston Holdings, Inc.|NYSE
OVV|Ovintiv Inc.|NYSE
CCI|Crown Castle Inc.|NYSE
GIS|General Mills, Inc.|NYSE
TAP|Molson Coors Beverage Company|NYSE
NTRA|Natera, Inc.|NASDAQ
LMCA|Liberty Media Corporation|NASDAQ`;

const TOTAL = 9800;
const STEMS = ["Northwind","Cascade","Granite","Harborview","Sterling","Meridian","Kestrel",
  "Ironwood","Clearwater","Summit Ridge","Bluepoint","Redstone","Fairhaven","Lakeshore",
  "Copperline","Silverbrook","Pinecrest","Windmere","Ashford","Belmont","Crossgate",
  "Eastvale","Foxglove","Glenmoor","Havenbrook","Inglewood","Junction","Kingsford"];
const KINDS = ["Holdings","Industries","Technologies","Bancorp","Resources","Therapeutics",
  "Logistics","Materials","Energy Partners","Financial Group","Semiconductor","Systems",
  "Properties","Health","Networks","Foods","Capital","Instruments"];
const EXCHANGES = ["NYSE", "NASDAQ", "NYSE American"];
const A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

/* Deterministic, so the same symbol always describes the same company. */
function lcg(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

function buildUniverse() {
  const rows = REAL.trim().split("\n").map((line) => {
    const [symbol, name, exchange] = line.split("|");
    return { symbol, name, exchange, synthetic: false };
  });
  const taken = new Set(rows.map((r) => r.symbol));
  const rand = lcg(20260902);
  while (rows.length < TOTAL) {
    const len = 3 + Math.floor(rand() * 2);
    let symbol = "";
    for (let i = 0; i < len; i++) symbol += A[Math.floor(rand() * 26)];
    if (taken.has(symbol)) continue;
    taken.add(symbol);
    rows.push({
      symbol,
      name: `${STEMS[Math.floor(rand() * STEMS.length)]} ${KINDS[Math.floor(rand() * KINDS.length)]}`,
      exchange: EXCHANGES[Math.floor(rand() * EXCHANGES.length)],
      synthetic: true,
    });
  }
  return rows;
}

export const UNIVERSE = buildUniverse();
