"""
citategenie/detectors.py

Citation type detection logic.
Analyzes text patterns to determine the type of citation.

Version History:
    2025-12-20 V2.0: Added comprehensive newspaper/magazine detection (500+ publications)
"""

import re
from typing import Optional, Dict, Any
from models import CitationType, DetectionResult


# URL detection patterns
URL_PATTERN = re.compile(
    r'^https?://[^\s]+$|'
    r'^www\.[^\s]+$|'
    r'\bhttps?://[^\s]+',
    re.IGNORECASE
)

# DOI patterns
DOI_PATTERN = re.compile(
    r'(?:doi[:\s]*)?10\.\d{4,}/[^\s]+',
    re.IGNORECASE
)

# Legal citation patterns
LEGAL_PATTERNS = [
    re.compile(r'\d+\s+U\.?S\.?\s+\d+'),  # US Reports: 388 U.S. 1
    re.compile(r'\d+\s+S\.?\s*Ct\.?\s+\d+'),  # Supreme Court Reporter
    re.compile(r'\d+\s+F\.?\s*(?:2d|3d|4th)?\s+\d+'),  # Federal Reporter
    re.compile(r'\d+\s+F\.?\s*Supp\.?\s*(?:2d|3d)?\s+\d+'),  # Federal Supplement
    re.compile(r'\d+\s+[A-Z][a-z]*\.?\s*(?:2d|3d)?\s+\d+'),  # State reporters
    re.compile(r'\bv\.\s+', re.IGNORECASE),  # Case name indicator
    re.compile(r'\[\d{4}\]\s+[A-Z]+(?:\s+[A-Za-z]+)*\s+\d+'),  # UK neutral citation
]

# Book patterns - expanded to catch various book citation formats
BOOK_PATTERNS = [
    # ISBN patterns
    re.compile(r'ISBN[:\s]*[\d\-X]+', re.IGNORECASE),
    re.compile(r'\b97[89][\d\-]{10,}', re.IGNORECASE),  # ISBN-13 starting with 978/979
    
    # Publisher in parentheses: (New York: Oxford University Press, 1998)
    re.compile(r'\([^)]*:\s*[^)]+(?:Press|Publishers?|Books?|Publishing)[^)]*,\s*\d{4}\)', re.IGNORECASE),
    
    # Publisher without city: (Oxford University Press, 1998)
    re.compile(r'\([\w\s]+(?:Press|Publishers?|Books?|Publishing),?\s*\d{4}\)', re.IGNORECASE),
    
    # Common academic/trade publishers (without Press/Books suffix)
    re.compile(r'\(\s*(?:Knopf|Random\s*House|Penguin|HarperCollins|Simon\s*&\s*Schuster|Macmillan|Routledge|Sage|Wiley|Springer|Elsevier|Cambridge|Oxford|Harvard|Yale|Princeton|MIT|Chicago|Stanford|Duke|Cornell|Columbia|Berkeley|Michigan|Indiana|Minnesota|Wisconsin|Penn|Northwestern|Johns\s*Hopkins|Georgetown|NYU|Vintage|Anchor|Doubleday|Norton|Farrar|Houghton|Little\s*Brown|Scribner|Crown|Pantheon|Basic|Free\s*Press|Hill\s*and\s*Wang|Grove|Beacon|Riverhead|Ecco|Bloomsbury|Verso|Polity|Palgrave|Academic\s*Press|W\.?\s*H\.?\s*Freeman|Henry\s*Holt|Holt|McGraw[\s\-]*Hill|Addison[\s\-]*Wesley|Pearson|Cengage|Thomson|Worth|Guilford|Lawrence\s*Erlbaum|Psychology\s*Press|Taylor\s*&\s*Francis|Blackwell|John\s*Wiley|Jossey[\s\-]*Bass|Westview|Praeger|Greenwood|Rowman|Lexington|Transaction|M\.?\s*E\.?\s*Sharpe|Ashgate|Edward\s*Elgar|De\s*Gruyter|Brill|Kluwer|IOS|World\s*Scientific|CRC|Marcel\s*Dekker|Humana|Lippincott|Mosby|Saunders|Thieme|Karger)\b[^)]*,?\s*\d{4}\)', re.IGNORECASE),
    
    # "ed." or "eds." indicating edited volume
    re.compile(r'\bed(?:s)?\.?\s*(?:by\s+)?[A-Z][a-z]+', re.IGNORECASE),
    
    # "trans." or "translated by" 
    re.compile(r'\btrans(?:lated)?\.?\s*(?:by\s+)?[A-Z][a-z]+', re.IGNORECASE),
    
    # Edition indicators: "2nd ed.", "revised edition", etc.
    re.compile(r'\b(?:\d+(?:st|nd|rd|th)|revised|expanded|updated|abridged)\s+ed(?:ition)?\.?\b', re.IGNORECASE),
    
    # Volume/chapter in book: "vol. 2" or "chapter 5" (but not journal volumes)
    re.compile(r'\bchapter\s+\d+\b', re.IGNORECASE),
    
    # "In" followed by italicized/quoted title (book chapter pattern)
    re.compile(r'\bIn\s+[A-Z][^,]+,\s*ed(?:s)?\.?\s+(?:by\s+)?[A-Z]', re.IGNORECASE),
    
    # City: Publisher pattern without parentheses
    re.compile(r'\b(?:New\s*York|London|Cambridge|Oxford|Chicago|Boston|Philadelphia|Princeton|Berkeley|Stanford|Durham|Chapel\s*Hill|Ithaca|New\s*Haven|Baltimore|Los\s*Angeles|San\s*Francisco|Washington|Toronto|Montreal|Paris|Berlin|Amsterdam|Tokyo):\s*[A-Z][\w\s&]+,\s*\d{4}\b', re.IGNORECASE),
]

# Interview patterns
INTERVIEW_PATTERNS = [
    re.compile(r'interview\s+(?:by|with)', re.IGNORECASE),
    re.compile(r'oral\s+history', re.IGNORECASE),
    re.compile(r'personal\s+communication', re.IGNORECASE),
]

# =============================================================================
# COMPREHENSIVE NEWSPAPER/MAGAZINE DATABASE
# =============================================================================

# Newspaper URL domains (for URL-based detection)
NEWSPAPER_DOMAINS = [
    'nytimes.com', 'washingtonpost.com', 'wsj.com', 'theguardian.com',
    'bbc.com', 'reuters.com', 'apnews.com', 'cnn.com', 'latimes.com',
    'usatoday.com', 'chicagotribune.com', 'bostonglobe.com', 'sfchronicle.com',
    'theatlantic.com', 'newyorker.com', 'politico.com', 'axios.com',
    'bloomberg.com', 'ft.com', 'economist.com', 'forbes.com',
    'time.com', 'newsweek.com', 'huffpost.com', 'vox.com', 'slate.com',
    'npr.org', 'pbs.org', 'cbsnews.com', 'nbcnews.com', 'abcnews.go.com',
    'foxnews.com', 'msnbc.com', 'thehill.com', 'dailybeast.com',
    'thedailybeast.com', 'motherjones.com', 'nationalreview.com',
    'theverge.com', 'wired.com', 'arstechnica.com', 'techcrunch.com',
    'statnews.com', 'scientificamerican.com', 'nature.com', 'sciencemag.org',
    'telegraph.co.uk', 'independent.co.uk', 'dailymail.co.uk', 'mirror.co.uk',
    'thesun.co.uk', 'thetimes.co.uk', 'standard.co.uk', 'metro.co.uk',
    'globeandmail.com', 'thestar.com', 'nationalpost.com', 'cbc.ca',
    'smh.com.au', 'theaustralian.com.au', 'abc.net.au', 'news.com.au',
    'nzherald.co.nz', 'stuff.co.nz', 'rnz.co.nz',
    'lemonde.fr', 'lefigaro.fr', 'liberation.fr', 'lepoint.fr',
    'spiegel.de', 'zeit.de', 'faz.net', 'sueddeutsche.de', 'bild.de',
    'elpais.com', 'elmundo.es', 'abc.es', 'lavanguardia.com',
    'corriere.it', 'repubblica.it', 'lastampa.it', 'ilsole24ore.com',
    'clarin.com', 'lanacion.com.ar', 'infobae.com',
    'folha.uol.com.br', 'oglobo.globo.com', 'estadao.com.br',
    'eluniversal.com.mx', 'reforma.com', 'milenio.com', 'jornada.com.mx',
    'eltiempo.com', 'elespectador.com', 'semana.com',
    'emol.com', 'latercera.com', 'elmercurio.com',
    'elcomercio.pe', 'larepublica.pe', 'gestion.pe',
]

# Newspaper/Magazine names (for text-based citation detection)
# Organized by region for maintainability
NEWSPAPER_NAMES = {
    # ==========================================================================
    # UNITED STATES - Major National
    # ==========================================================================
    'us_national': [
        'New York Times', 'The New York Times', 'NYT', 'N.Y. Times',
        'Washington Post', 'The Washington Post', 'WaPo',
        'Wall Street Journal', 'The Wall Street Journal', 'WSJ',
        'USA Today', 'USA TODAY',
        'Los Angeles Times', 'The Los Angeles Times', 'LA Times', 'L.A. Times',
        'Chicago Tribune', 'The Chicago Tribune',
        'New York Post', 'The New York Post', 'NY Post',
        'New York Daily News', 'Daily News',
        'Newsday',
        'Boston Globe', 'The Boston Globe',
        'San Francisco Chronicle', 'SF Chronicle', 'S.F. Chronicle',
        'Houston Chronicle', 'The Houston Chronicle',
        'Dallas Morning News', 'The Dallas Morning News',
        'Philadelphia Inquirer', 'The Philadelphia Inquirer',
        'Arizona Republic', 'The Arizona Republic',
        'Denver Post', 'The Denver Post',
        'Minneapolis Star Tribune', 'Star Tribune',
        'Tampa Bay Times',
        'Miami Herald', 'The Miami Herald',
        'Atlanta Journal-Constitution', 'The Atlanta Journal-Constitution', 'AJC',
        'Seattle Times', 'The Seattle Times',
        'San Diego Union-Tribune', 'The San Diego Union-Tribune',
        'Orange County Register', 'The Orange County Register',
        'St. Louis Post-Dispatch', 'Post-Dispatch',
        'Baltimore Sun', 'The Baltimore Sun',
        'Detroit Free Press', 'The Detroit Free Press',
        'Cleveland Plain Dealer', 'The Plain Dealer',
        'Pittsburgh Post-Gazette', 'Post-Gazette',
        'Portland Oregonian', 'The Oregonian',
        'Sacramento Bee', 'The Sacramento Bee',
        'San Jose Mercury News', 'Mercury News',
        'Las Vegas Review-Journal', 'Review-Journal',
        'Kansas City Star', 'The Kansas City Star',
        'Milwaukee Journal Sentinel', 'Journal Sentinel',
        'Indianapolis Star', 'The Indianapolis Star',
        'Cincinnati Enquirer', 'The Cincinnati Enquirer',
        'Columbus Dispatch', 'The Columbus Dispatch',
        'Charlotte Observer', 'The Charlotte Observer',
        'Raleigh News & Observer', 'News & Observer',
        'Orlando Sentinel', 'The Orlando Sentinel',
        'Hartford Courant', 'The Hartford Courant',
        'Providence Journal', 'The Providence Journal',
        'Honolulu Star-Advertiser', 'Star-Advertiser',
        'Anchorage Daily News',
    ],
    
    # ==========================================================================
    # UNITED STATES - News Magazines & Digital
    # ==========================================================================
    'us_magazines': [
        'Time', 'Time Magazine',
        'Newsweek',
        'The Atlantic', 'Atlantic Monthly',
        'The New Yorker', 'New Yorker',
        'Harper\'s Magazine', 'Harper\'s', 'Harpers',
        'The Nation',
        'The New Republic', 'New Republic', 'TNR',
        'National Review',
        'The Weekly Standard', 'Weekly Standard',
        'Mother Jones',
        'Reason', 'Reason Magazine',
        'The American Conservative',
        'Commentary', 'Commentary Magazine',
        'Foreign Affairs',
        'Foreign Policy',
        'The American Prospect',
        'Jacobin', 'Jacobin Magazine',
        'Current Affairs',
        'Dissent', 'Dissent Magazine',
        'n+1',
    ],
    
    # ==========================================================================
    # UNITED STATES - Digital Native
    # ==========================================================================
    'us_digital': [
        'HuffPost', 'Huffington Post', 'The Huffington Post',
        'Politico', 'POLITICO',
        'Axios',
        'Vox',
        'Slate', 'Slate Magazine',
        'Salon',
        'BuzzFeed', 'BuzzFeed News',
        'The Daily Beast', 'Daily Beast',
        'The Intercept', 'Intercept',
        'ProPublica',
        'The Marshall Project', 'Marshall Project',
        'FiveThirtyEight', '538',
        'Quartz', 'Quartz Media',
        'The Ringer',
        'Defector',
        'The Information',
        'Puck', 'Puck News',
        'Semafor',
        'The Messenger',
        'Grid', 'Grid News',
        'The 19th', '19th News',
        'Capital B',
        'The Lever',
        'Hell Gate',
        'Insider', 'Business Insider',
    ],
    
    # ==========================================================================
    # UNITED STATES - Wire Services & Broadcast
    # ==========================================================================
    'us_wire_broadcast': [
        'Associated Press', 'The Associated Press', 'AP', 'AP News',
        'Reuters',
        'United Press International', 'UPI',
        'Agence France-Presse', 'AFP',
        'Bloomberg', 'Bloomberg News', 'Bloomberg Businessweek',
        'NPR', 'National Public Radio',
        'PBS', 'PBS NewsHour', 'NewsHour',
        'CNN', 'CNN.com',
        'MSNBC',
        'Fox News', 'FOX News',
        'CBS News',
        'NBC News',
        'ABC News',
        'C-SPAN',
    ],
    
    # ==========================================================================
    # UNITED STATES - Business & Finance
    # ==========================================================================
    'us_business': [
        'Forbes', 'Forbes Magazine',
        'Fortune', 'Fortune Magazine',
        'Barron\'s', 'Barrons',
        'MarketWatch',
        'Investor\'s Business Daily', 'IBD',
        'American Banker',
        'Financial Times', 'The Financial Times', 'FT',
        'The Economist', 'Economist',
    ],
    
    # ==========================================================================
    # UNITED STATES - Tech
    # ==========================================================================
    'us_tech': [
        'Wired', 'WIRED', 'Wired Magazine',
        'The Verge',
        'Ars Technica',
        'TechCrunch',
        'Engadget',
        'Gizmodo',
        'Mashable',
        'CNET',
        'ZDNet',
        'VentureBeat',
        'The Information',
        'Protocol',
        'Recode',
        '9to5Mac', '9to5Google',
        'MacRumors',
        'Tom\'s Hardware', 'Tom\'s Guide',
        'AnandTech',
    ],
    
    # ==========================================================================
    # UNITED STATES - Science & Health
    # ==========================================================================
    'us_science_health': [
        'Scientific American',
        'Popular Science', 'PopSci',
        'Popular Mechanics',
        'Discover', 'Discover Magazine',
        'Science News',
        'MIT Technology Review', 'Technology Review',
        'Stat', 'Stat News', 'STAT', 'STAT News',
        'Verywell Health',
        'Health', 'Health Magazine',
        'Prevention', 'Prevention Magazine',
        'WebMD',
        'Healthline',
        'Medical News Today',
        'Medscape',
        'MedPage Today',
        'Kaiser Health News', 'KHN', 'KFF Health News',
        'Undark', 'Undark Magazine',
        'Nautilus', 'Nautilus Magazine',
        'Quanta', 'Quanta Magazine',
    ],
    
    # ==========================================================================
    # UNITED STATES - Politics & Policy
    # ==========================================================================
    'us_politics': [
        'The Hill',
        'Roll Call',
        'Congressional Quarterly', 'CQ',
        'National Journal',
        'The American Interest',
        'Lawfare',
        'Just Security',
        'War on the Rocks',
        'Defense One',
        'Government Executive',
        'Federal Times',
        'Stars and Stripes',
        'Military Times',
    ],
    
    # ==========================================================================
    # UNITED STATES - Culture & Entertainment
    # ==========================================================================
    'us_entertainment': [
        'Vanity Fair',
        'GQ', 'Gentlemen\'s Quarterly',
        'Esquire',
        'Rolling Stone',
        'Variety',
        'The Hollywood Reporter', 'Hollywood Reporter', 'THR',
        'Deadline', 'Deadline Hollywood',
        'Entertainment Weekly', 'EW',
        'People', 'People Magazine',
        'Us Weekly',
        'InStyle',
        'Vogue', 'Vogue Magazine',
        'Elle', 'ELLE',
        'W Magazine',
        'Harper\'s Bazaar',
        'Cosmopolitan', 'Cosmo',
        'Glamour',
        'Billboard',
        'Pitchfork',
        'Spin', 'SPIN',
        'NME',
        'The A.V. Club', 'AV Club',
        'Vulture',
        'IndieWire',
        'Screen Rant',
        'IGN',
        'Polygon',
        'Kotaku',
        'The Root',
        'Essence',
        'Ebony',
        'Jet',
    ],
    
    # ==========================================================================
    # UNITED STATES - Sports
    # ==========================================================================
    'us_sports': [
        'Sports Illustrated', 'SI',
        'ESPN', 'ESPN The Magazine',
        'The Athletic',
        'Bleacher Report',
        'Sporting News', 'The Sporting News',
        'Sports Business Journal', 'SBJ',
        'Golf Digest',
        'Golf Magazine',
        'Tennis', 'Tennis Magazine',
        'Runner\'s World',
        'Bicycling',
        'Ski', 'Ski Magazine',
        'Outside', 'Outside Magazine',
        'Field & Stream',
        'Outdoor Life',
    ],
    
    # ==========================================================================
    # UNITED KINGDOM
    # ==========================================================================
    'uk': [
        'The Guardian', 'Guardian',
        'The Observer', 'Observer',
        'The Times', 'Times of London', 'The Times of London',
        'The Sunday Times', 'Sunday Times',
        'The Daily Telegraph', 'Daily Telegraph', 'The Telegraph', 'Telegraph',
        'The Sunday Telegraph', 'Sunday Telegraph',
        'The Independent', 'Independent',
        'i', 'i newspaper',
        'Daily Mail', 'The Daily Mail', 'Mail on Sunday',
        'Daily Mirror', 'The Mirror', 'Sunday Mirror',
        'The Sun', 'Sun',
        'Daily Express', 'The Express', 'Sunday Express',
        'Daily Star', 'The Star',
        'Metro',
        'Evening Standard', 'The Evening Standard', 'London Evening Standard',
        'City A.M.', 'City AM',
        'The Scotsman', 'Scotsman',
        'The Herald', 'Glasgow Herald',
        'Daily Record', 'Sunday Mail',
        'The Press and Journal',
        'Western Mail',
        'Belfast Telegraph',
        'Irish News',
        'The Irish Times', 'Irish Times',
        'Irish Independent',
        'The Spectator', 'Spectator',
        'New Statesman', 'The New Statesman',
        'The Week',
        'Private Eye',
        'The Economist',
        'Financial Times', 'FT',
    ],
    
    # ==========================================================================
    # CANADA
    # ==========================================================================
    'canada': [
        'The Globe and Mail', 'Globe and Mail',
        'National Post', 'The National Post',
        'Toronto Star', 'The Toronto Star', 'The Star',
        'Toronto Sun', 'The Sun',
        'Montreal Gazette', 'The Gazette',
        'La Presse',
        'Le Devoir',
        'Le Journal de Montréal', 'Le Journal de Montreal',
        'Vancouver Sun', 'The Vancouver Sun',
        'The Province',
        'Calgary Herald', 'The Calgary Herald',
        'Edmonton Journal', 'The Edmonton Journal',
        'Ottawa Citizen', 'The Ottawa Citizen',
        'Winnipeg Free Press',
        'Halifax Chronicle Herald', 'The Chronicle Herald',
        'CBC News', 'CBC',
        'CTV News', 'CTV',
        'Global News',
        'Maclean\'s', 'Macleans',
        'The Walrus', 'Walrus',
        'Toronto Life',
        'Canadian Business',
    ],
    
    # ==========================================================================
    # AUSTRALIA
    # ==========================================================================
    'australia': [
        'The Australian', 'Australian',
        'The Sydney Morning Herald', 'Sydney Morning Herald', 'SMH',
        'The Age', 'Age',
        'The Daily Telegraph', 'Daily Telegraph',
        'Herald Sun', 'The Herald Sun',
        'The Courier-Mail', 'Courier-Mail', 'Courier Mail',
        'The Advertiser', 'Advertiser',
        'The West Australian', 'West Australian',
        'The Mercury',
        'The Canberra Times', 'Canberra Times',
        'Australian Financial Review', 'AFR', 'The AFR',
        'The Saturday Paper', 'Saturday Paper',
        'Crikey',
        'The Monthly', 'Monthly',
        'The Guardian Australia', 'Guardian Australia',
        'ABC News', 'ABC', 'Australian Broadcasting Corporation',
        'SBS News', 'SBS',
        'Nine News', 'Nine',
        'Seven News', 'Seven',
        'news.com.au',
    ],
    
    # ==========================================================================
    # NEW ZEALAND
    # ==========================================================================
    'new_zealand': [
        'The New Zealand Herald', 'New Zealand Herald', 'NZ Herald',
        'Stuff', 'Stuff.co.nz',
        'The Press',
        'The Dominion Post', 'Dominion Post',
        'Otago Daily Times',
        'Waikato Times',
        'The Listener', 'New Zealand Listener', 'NZ Listener',
        'North & South',
        'Metro',
        'RNZ', 'Radio New Zealand',
        'Newshub',
        'TVNZ',
        '1 News', 'One News',
        'Newsroom', 'Newsroom.co.nz',
        'The Spinoff', 'Spinoff',
    ],
    
    # ==========================================================================
    # EUROPE - France
    # ==========================================================================
    'france': [
        'Le Monde',
        'Le Figaro',
        'Libération', 'Liberation',
        'Les Échos', 'Les Echos',
        'Le Parisien',
        'Aujourd\'hui en France',
        'L\'Équipe', 'L\'Equipe', 'L Equipe',
        'Le Point',
        'L\'Express', 'L Express',
        'L\'Obs', 'L Obs', 'Le Nouvel Observateur',
        'Marianne',
        'Paris Match',
        'Mediapart',
        'La Croix',
        'Ouest-France',
        'Sud Ouest',
        'La Voix du Nord',
        'Le Télégramme', 'Le Telegramme',
        'Nice-Matin',
        'La Provence',
        'France 24',
        'RFI', 'Radio France Internationale',
    ],
    
    # ==========================================================================
    # EUROPE - Germany
    # ==========================================================================
    'germany': [
        'Der Spiegel', 'Spiegel', 'SPIEGEL',
        'Die Zeit', 'ZEIT', 'Zeit',
        'Frankfurter Allgemeine Zeitung', 'FAZ', 'Frankfurter Allgemeine',
        'Süddeutsche Zeitung', 'Sueddeutsche Zeitung', 'SZ',
        'Die Welt', 'Welt',
        'Bild', 'BILD',
        'Handelsblatt',
        'Wirtschaftswoche', 'WirtschaftsWoche',
        'Focus', 'FOCUS',
        'Stern',
        'Tagesspiegel', 'Der Tagesspiegel',
        'Frankfurter Rundschau',
        'taz', 'die tageszeitung',
        'Berliner Zeitung',
        'Hamburger Abendblatt',
        'Rheinische Post',
        'Deutsche Welle', 'DW',
    ],
    
    # ==========================================================================
    # EUROPE - Spain
    # ==========================================================================
    'spain': [
        'El País', 'El Pais',
        'El Mundo',
        'ABC',
        'La Vanguardia',
        'El Periódico', 'El Periodico',
        'La Razón', 'La Razon',
        '20 Minutos', '20 minutos',
        'El Confidencial',
        'elDiario.es', 'eldiario.es',
        'Público', 'Publico',
        'Expansión', 'Expansion',
        'Cinco Días', 'Cinco Dias',
        'Marca',
        'As', 'AS',
        'Mundo Deportivo',
        'Sport',
        'El Correo',
        'El Diario Vasco',
        'La Voz de Galicia',
        'Heraldo de Aragón', 'Heraldo de Aragon',
        'Levante', 'Levante-EMV',
    ],
    
    # ==========================================================================
    # EUROPE - Italy
    # ==========================================================================
    'italy': [
        'Corriere della Sera', 'Corriere',
        'La Repubblica', 'Repubblica',
        'La Stampa', 'Stampa',
        'Il Sole 24 Ore', 'Sole 24 Ore',
        'Il Messaggero', 'Messaggero',
        'Il Giornale', 'Giornale',
        'Libero', 'Libero Quotidiano',
        'Il Fatto Quotidiano', 'Fatto Quotidiano',
        'Avvenire',
        'Il Manifesto', 'Manifesto',
        'La Gazzetta dello Sport', 'Gazzetta dello Sport',
        'Corriere dello Sport',
        'Tuttosport',
        'L\'Espresso', 'Espresso',
        'Panorama',
        'Il Foglio', 'Foglio',
        'Domani',
        'Il Post',
    ],
    
    # ==========================================================================
    # EUROPE - Other
    # ==========================================================================
    'europe_other': [
        # Netherlands
        'De Telegraaf', 'Telegraaf',
        'de Volkskrant', 'Volkskrant',
        'NRC Handelsblad', 'NRC',
        'Trouw',
        'Het Parool', 'Parool',
        'Algemeen Dagblad', 'AD',
        # Belgium
        'De Standaard', 'Standaard',
        'De Morgen',
        'Het Laatste Nieuws',
        'Le Soir',
        'La Libre Belgique',
        # Switzerland
        'Neue Zürcher Zeitung', 'NZZ',
        'Tages-Anzeiger',
        'Blick',
        'Le Temps',
        '24 Heures',
        'Tribune de Genève',
        # Austria
        'Der Standard', 'Standard',
        'Die Presse', 'Presse',
        'Kurier',
        'Kronen Zeitung', 'Krone',
        'Salzburger Nachrichten',
        # Portugal
        'Público',
        'Diário de Notícias', 'Diario de Noticias',
        'Jornal de Notícias',
        'Expresso',
        'Observador',
        # Ireland
        'The Irish Times', 'Irish Times',
        'Irish Independent',
        'Irish Examiner',
        'Sunday Independent',
        'Sunday Business Post',
        # Scandinavia
        'Aftenposten',
        'Dagbladet',
        'VG', 'Verdens Gang',
        'Dagens Nyheter', 'DN',
        'Svenska Dagbladet', 'SvD',
        'Expressen',
        'Aftonbladet',
        'Helsingin Sanomat', 'HS',
        'Ilta-Sanomat',
        'Politiken',
        'Berlingske',
        'Jyllands-Posten',
        'Ekstra Bladet',
        # Poland
        'Gazeta Wyborcza',
        'Rzeczpospolita',
        'Dziennik Gazeta Prawna',
        # Greece
        'Kathimerini',
        'Ta Nea',
        'To Vima',
    ],
    
    # ==========================================================================
    # LATIN AMERICA - Mexico
    # ==========================================================================
    'mexico': [
        'El Universal',
        'Reforma',
        'La Jornada',
        'Milenio',
        'Excélsior', 'Excelsior',
        'El Financiero',
        'El Economista',
        'El Sol de México', 'El Sol de Mexico',
        'El Heraldo de México', 'El Heraldo de Mexico',
        'Proceso',
        'Letras Libres',
        'Nexos',
        'Animal Político', 'Animal Politico',
        'Sin Embargo',
        'Aristegui Noticias',
    ],
    
    # ==========================================================================
    # LATIN AMERICA - Brazil
    # ==========================================================================
    'brazil': [
        'Folha de S.Paulo', 'Folha de S. Paulo', 'Folha de São Paulo', 'Folha',
        'O Globo', 'Globo',
        'O Estado de S. Paulo', 'Estadão', 'Estadao',
        'Valor Econômico', 'Valor Economico',
        'Correio Braziliense',
        'Zero Hora',
        'O Povo',
        'Jornal do Brasil',
        'Veja',
        'IstoÉ', 'Isto E', 'IstoE',
        'Época', 'Epoca',
        'CartaCapital', 'Carta Capital',
        'Piauí', 'Piaui', 'revista piauí',
        'The Brazilian Report',
        'G1',
        'UOL',
    ],
    
    # ==========================================================================
    # LATIN AMERICA - Argentina
    # ==========================================================================
    'argentina': [
        'Clarín', 'Clarin',
        'La Nación', 'La Nacion',
        'Página/12', 'Pagina 12', 'Página 12',
        'Infobae',
        'Perfil',
        'Ámbito Financiero', 'Ambito Financiero', 'Ámbito', 'Ambito',
        'El Cronista',
        'La Voz del Interior', 'La Voz',
        'Los Andes',
        'Télam', 'Telam',
    ],
    
    # ==========================================================================
    # LATIN AMERICA - Other
    # ==========================================================================
    'latam_other': [
        # Colombia
        'El Tiempo',
        'El Espectador',
        'Semana',
        'La República', 'La Republica',
        'Portafolio',
        # Chile
        'El Mercurio',
        'La Tercera',
        'La Segunda',
        'El Mostrador',
        'Ciper', 'CIPER Chile',
        'The Clinic',
        # Peru
        'El Comercio',
        'La República',
        'Gestión', 'Gestion',
        'Peru21', 'Perú21',
        'Correo',
        'Ojo Público', 'Ojo Publico',
        'IDL-Reporteros',
        # Venezuela
        'El Nacional',
        'El Universal',
        'Tal Cual',
        'Efecto Cocuyo',
        'Runrun.es',
        'Prodavinci',
        # Ecuador
        'El Comercio',
        'El Universo',
        'Expreso',
        'La Hora',
        'Plan V',
        # Uruguay
        'El País', 'El Pais',
        'El Observador',
        'La Diaria',
        'Búsqueda', 'Busqueda',
        # Central America
        'La Prensa Gráfica', 'La Prensa Grafica',
        'El Diario de Hoy',
        'La Prensa',
        'El Heraldo',
        'La Nación', 'La Nacion',
        'Prensa Libre',
        'El Periódico', 'El Periodico',
        # Caribbean
        'El Nuevo Día', 'El Nuevo Dia',
        'Primera Hora',
        'Diario Libre',
        'Listín Diario', 'Listin Diario',
        'Jamaica Gleaner', 'The Gleaner',
        'Jamaica Observer',
        'Trinidad Guardian',
        'Trinidad Express',
    ],
    
    # ==========================================================================
    # ASIA (major English-language)
    # ==========================================================================
    'asia': [
        # India
        'The Times of India', 'Times of India', 'TOI',
        'Hindustan Times', 'HT',
        'The Hindu',
        'The Indian Express', 'Indian Express',
        'The Economic Times', 'Economic Times', 'ET',
        'Business Standard',
        'Mint',
        'The Telegraph',
        'Deccan Herald',
        'The Statesman',
        'The Tribune',
        'The Wire',
        'Scroll.in', 'Scroll',
        'The Print', 'ThePrint',
        'Firstpost',
        'News18',
        'NDTV',
        # Japan
        'The Japan Times', 'Japan Times',
        'Nikkei Asia', 'Nikkei',
        'The Asahi Shimbun', 'Asahi Shimbun',
        'The Mainichi', 'Mainichi Shimbun',
        'The Yomiuri Shimbun', 'Yomiuri',
        # South Korea
        'The Korea Herald', 'Korea Herald',
        'The Korea Times', 'Korea Times',
        'The Chosun Ilbo', 'Chosun Ilbo',
        'JoongAng Ilbo', 'JoongAng Daily',
        # China/Hong Kong
        'South China Morning Post', 'SCMP',
        'Hong Kong Free Press', 'HKFP',
        'The Standard',
        'China Daily',
        'Global Times',
        # Singapore
        'The Straits Times', 'Straits Times',
        'Today',
        'Channel NewsAsia', 'CNA',
        # Southeast Asia
        'The Bangkok Post', 'Bangkok Post',
        'The Nation',
        'Manila Bulletin',
        'Philippine Daily Inquirer', 'Inquirer',
        'Philippine Star',
        'Rappler',
        'The Jakarta Post', 'Jakarta Post',
        'Kompas',
        'Tempo',
        'New Straits Times',
        'The Star',
        'Malaysiakini',
        'Vietnam News',
        'VnExpress',
    ],
    
    # ==========================================================================
    # MIDDLE EAST & AFRICA
    # ==========================================================================
    'middle_east_africa': [
        # Middle East
        'Haaretz',
        'The Jerusalem Post', 'Jerusalem Post',
        'Times of Israel',
        'Yedioth Ahronoth', 'Ynet',
        'Al Jazeera', 'Al-Jazeera',
        'Al Arabiya',
        'The National',
        'Gulf News',
        'Khaleej Times',
        'Arab News',
        'Daily Star',
        'L\'Orient-Le Jour', 'L\'Orient Le Jour',
        'Al-Monitor',
        'Middle East Eye',
        # Africa
        'Daily Maverick',
        'Mail & Guardian', 'Mail and Guardian',
        'News24',
        'Business Day',
        'The Star',
        'Sunday Times',
        'City Press',
        'TimesLIVE',
        'IOL',
        'Sowetan',
        'Daily Nation',
        'The East African',
        'The Standard',
        'The Citizen',
        'This Day',
        'The Punch',
        'Vanguard',
        'Premium Times',
        'The Guardian Nigeria',
        'Daily Trust',
        'Al-Ahram', 'Al Ahram',
        'Egypt Independent',
        'Mada Masr',
    ],
}

# Flatten all newspaper names into a single list
ALL_NEWSPAPER_NAMES = []
for category in NEWSPAPER_NAMES.values():
    ALL_NEWSPAPER_NAMES.extend(category)

# Remove duplicates while preserving order
seen = set()
UNIQUE_NEWSPAPER_NAMES = []
for name in ALL_NEWSPAPER_NAMES:
    if name.lower() not in seen:
        seen.add(name.lower())
        UNIQUE_NEWSPAPER_NAMES.append(name)

# Pre-compile newspaper name pattern for efficiency
# Sort by length (longest first) to match "The New York Times" before "Times"
SORTED_NAMES = sorted(UNIQUE_NEWSPAPER_NAMES, key=len, reverse=True)
NEWSPAPER_NAME_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(name) for name in SORTED_NAMES) + r')\b',
    re.IGNORECASE
)


def is_url(text: str) -> bool:
    """Check if text is or contains a URL."""
    if not text:
        return False
    return bool(URL_PATTERN.search(text.strip()))


def detect_type(query: str) -> DetectionResult:
    """
    Detect the type of citation from the query text.
    
    Args:
        query: The citation text to analyze
        
    Returns:
        DetectionResult with type, confidence, and hints
    """
    if not query:
        return DetectionResult(CitationType.UNKNOWN, 0.0, "")
    
    query = query.strip()
    cleaned = query
    hints = {}
    
    # Check for DOI
    doi_match = DOI_PATTERN.search(query)
    if doi_match:
        hints['doi'] = doi_match.group()
        return DetectionResult(CitationType.JOURNAL, 0.95, cleaned, hints)
    
    # Check for URL
    if is_url(query):
        # Check for newspaper domains
        lower_query = query.lower()
        for domain in NEWSPAPER_DOMAINS:
            if domain in lower_query:
                return DetectionResult(CitationType.NEWSPAPER, 0.9, cleaned, {'url': query})
        return DetectionResult(CitationType.URL, 0.9, cleaned, {'url': query})
    
    # Check for legal citations
    for pattern in LEGAL_PATTERNS:
        if pattern.search(query):
            return DetectionResult(CitationType.LEGAL, 0.85, cleaned, hints)
    
    # Check for interview
    for pattern in INTERVIEW_PATTERNS:
        if pattern.search(query):
            return DetectionResult(CitationType.INTERVIEW, 0.9, cleaned, hints)
    
    # Check for newspaper/magazine names in text (before book check)
    newspaper_match = NEWSPAPER_NAME_PATTERN.search(query)
    if newspaper_match:
        hints['newspaper'] = newspaper_match.group(1)
        return DetectionResult(CitationType.NEWSPAPER, 0.85, cleaned, hints)
    
    # Check for book indicators
    for pattern in BOOK_PATTERNS:
        if pattern.search(query):
            return DetectionResult(CitationType.BOOK, 0.8, cleaned, hints)
    
    # Default to unknown - let AI classify
    return DetectionResult(CitationType.UNKNOWN, 0.5, cleaned, hints)
