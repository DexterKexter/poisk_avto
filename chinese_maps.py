"""Chinese → English translation maps shared across CN-source scrapers (che168, guazi).

Brand-name targets are aligned with autocango brand catalog so that cars match
`model_variants` rows by `brand_name` when displaying spec data.
"""

BRAND_MAP = {
    "奔驰": "Mercedes-Benz", "宝马": "BMW", "奥迪": "Audi", "大众": "Volkswagen",
    "丰田": "Toyota", "本田": "Honda", "日产": "Nissan", "马自达": "Mazda",
    "雷克萨斯": "Lexus", "英菲尼迪": "Infiniti", "讴歌": "Acura",
    "福特": "Ford", "雪佛兰": "Chevrolet", "凯迪拉克": "Cadillac", "别克": "Buick",
    "特斯拉": "Tesla", "比亚迪": "BYD", "吉利": "Geely", "吉利汽车": "Geely",
    "长城": "Great Wall", "长安": "Changan", "奇瑞": "Chery", "奇瑞QQ": "Chery",
    "哈弗": "Haval",
    "红旗": "Hongqi", "蔚来": "NIO", "小鹏": "XPeng", "小鹏汽车": "XPeng",
    "理想": "Li Auto", "理想汽车": "Li Auto", "零跑": "Leapmotor",
    "零跑汽车": "Leapmotor", "小米": "Xiaomi", "小米汽车": "Xiaomi",
    "AITO": "AITO", "问界": "AITO", "极氪": "Zeekr", "捷豹": "Jaguar",
    "路虎": "Land Rover", "保时捷": "Porsche", "玛莎拉蒂": "Maserati",
    "法拉利": "Ferrari", "兰博基尼": "Lamborghini", "宾利": "Bentley",
    "劳斯莱斯": "Rolls-Royce", "沃尔沃": "Volvo", "现代": "Hyundai", "起亚": "Kia",
    "标致": "Peugeot", "雪铁龙": "Citroen", "雷诺": "Renault", "斯柯达": "Skoda",
    "斯巴鲁": "Subaru", "三菱": "Mitsubishi", "铃木": "Suzuki",
    "smart": "smart", "MINI": "MINI", "MG": "MG", "名爵": "MG",
    "上汽大众": "SAIC Volkswagen", "上汽通用五菱": "Wuling", "五菱": "Wuling",
    "五菱汽车": "Wuling", "广汽传祺": "GAC Trumpchi", "传祺": "GAC Trumpchi",
    "坦克": "Tank", "腾势": "Denza", "仰望": "YangWang",
    "领克": "Lynk & Co", "WEY": "WEY", "魏牌": "WEY",
    "荣威": "Roewe", "宝骏": "Baojun", "东风": "Dongfeng",
    "东风风行": "Dongfeng Forthing", "东风风神": "Dongfeng Aeolus",
    "东风风光": "Dongfeng Fengguang", "东风小康": "Dongfeng Sokon",
    "东风奕派": "DongFeng eπ", "奕派": "DongFeng eπ",
    "猎豹": "Liebao", "猎豹汽车": "Liebao",
    "中华": "Brilliance", "华晨": "Brilliance",
    "北京汽车": "BAIC", "北汽新能源": "BAIC BJEV", "北京越野": "BAW",
    "智己": "IM", "智己汽车": "IM",
    "极狐": "ARCFOX", "ARCFOX极狐": "ARCFOX",
    "思皓": "Sehol", "凌宝汽车": "Lingbao", "凌宝": "Lingbao",
    "思铭": "Honda", "本田思铭": "Honda",
    "鸿蒙智行": "HIMA",  # Huawei alliance umbrella (sub-brand resolved via SERIES_TO_BRAND)
    "鸿蒙": "HIMA",
    "广汽本田": "GAC Honda", "理念": "Everus", "本田理念": "Everus",
    "远程": "Farizon", "远程星享V": "Farizon",  # Geely commercial EV brand
    "北京汽车": "BAIC", "北京": "BAIC",
    "ORA": "GWM Ora", "Ora": "GWM Ora",
    "LYNK&CO": "Lynk & Co", "Lynkco": "Lynk & Co", "LYNKCO": "Lynk & Co",
    "MI": "Xiaomi", "XIAOMI": "Xiaomi", "ONVO": "Onvo",
    "东风风光": "Dongfeng Fengguang", "风光": "Dongfeng Fengguang",
    "埃安": "Aion", "广汽埃安": "Aion", "AION": "Aion", "Aion": "Aion",
    "奔腾": "Bestune", "一汽奔腾": "Bestune",
    "岚图": "Voyah", "岚图汽车": "Voyah",
    "捷达": "Jetta",
    "吉利银河": "Geely Galaxy", "银河": "Geely Galaxy",
    "几何": "Geometry", "几何汽车": "Geometry", "吉利几何": "Geometry",
    "睿蓝": "Livan", "睿蓝汽车": "Livan",
    "方程豹": "FangChengBao",
    "启辰": "Venucia", "东风启辰": "Venucia",
    "广汽昊铂": "HYPTEC", "昊铂": "HYPTEC",
    "大通": "MAXUS", "上汽大通": "MAXUS",
    "长安欧尚": "ChangAn Oshan", "欧尚": "ChangAn Oshan",
    "汉腾": "HanTeng", "汉腾汽车": "HanTeng",
    "威马": "Weltmeister", "威马汽车": "Weltmeister",
    "飞凡": "Rising Auto", "飞凡汽车": "Rising Auto",
    "阿维塔": "AVATR", "智界": "Luxeed", "享界": "Stelato",
    "深蓝": "Deepal", "深蓝汽车": "Deepal", "启源": "Qiyuan",
    "长安启源": "Changan Qiyuan", "捷途": "Jetour", "星途": "Exeed",
    "凯翼": "Cowin", "江淮": "JAC", "江铃": "JMC", "海马": "Haima",
    "东南": "Soueast", "众泰": "Zotye", "力帆": "Lifan",
    "克莱斯勒": "Chrysler", "道奇": "Dodge", "Jeep": "Jeep",
    "林肯": "Lincoln", "捷尼赛思": "Genesis",
    "DS": "DS", "阿尔法罗密欧": "Alfa Romeo",
    "阿斯顿马丁": "Aston Martin", "阿斯顿·马丁": "Aston Martin",
    "迈凯伦": "McLaren", "布加迪": "Bugatti", "柯尼塞格": "Koenigsegg",
    "哪吒": "Neta", "哪吒汽车": "Neta", "高合": "HiPhi",
    "欧拉": "ORA", "欧拉汽车": "ORA",
    # CN/EN model-as-brand prefixes (che168 sometimes drops parent brand)
    "揽胜": "Land Rover", "卫士": "Land Rover", "发现": "Land Rover",
    "坦途": "Toyota", "陆地巡洋舰": "Toyota", "霸道": "Toyota",
    "途乐": "Nissan", "贵士": "Nissan",
    "Macan新能源": "Porsche", "卡宴": "Porsche",
    "Cayenne": "Porsche", "Macan": "Porsche", "Panamera": "Porsche",
    "Taycan": "Porsche", "Boxster": "Porsche", "Cayman": "Porsche",
    "迈巴赫": "Mercedes-Maybach",
    # Tesla (carname like "Model 3 2024款...")
    "Model 3": "Tesla", "Model Y": "Tesla", "Model S": "Tesla", "Model X": "Tesla",
    # Hyundai
    "Elantra": "Hyundai", "Tucson": "Hyundai", "Santa Fe": "Hyundai",
    "Sonata": "Hyundai", "Mistra": "Hyundai", "ix35": "Hyundai",
    "途胜": "Hyundai", "伊兰特": "Hyundai",
    # Subaru
    "傲虎": "Subaru", "力狮": "Subaru", "森林人": "Subaru",
    "翼豹": "Subaru", "BRZ": "Subaru",
    # Niche / luxury imports
    "摩根": "Morgan", "悍马": "Hummer", "Hummer": "Hummer",
    "莲花": "Lotus", "Lotus": "Lotus",
}


# SERIES_MAP — Chinese model/series name → official English
# Used by all CN-source scrapers (che168, guazi) and normalize_cars backfill.
# Targets are the manufacturer's official English model name (not pinyin).
SERIES_MAP = {
    # VW (China-specific lineup)
    "朗逸": "Lavida", "帕萨特": "Passat", "凌渡": "Lamando",
    "探岳": "Tayron", "探岳X": "Tayron X", "途岳": "Tharu",
    "途昂": "Teramont", "途昂X": "Teramont X", "途观": "Tiguan",
    "威然": "Viloran", "桑塔纳": "Santana", "宝来": "Bora",
    "高尔夫": "Golf", "速腾": "Jetta", "迈腾": "Magotan",
    "辉昂": "Phideon", "辉腾": "Phaeton", "蔚揽": "Variant",
    "夏朗": "Sharan", "途锐": "Touareg", "途铠": "T-Cross",
    "昕动": "Spaceback",
    # GM (Buick/Chevy/Cadillac China)
    "英朗": "Excelle GT", "威朗": "Verano", "威朗Pro": "Verano Pro",
    "君越": "LaCrosse", "君威": "Regal", "凯越": "Excelle",
    "世纪": "Century", "微蓝6": "Velite 6", "微蓝7": "Velite 7",
    "昂科威": "Envision", "昂科威Plus": "Envision Plus",
    "昂科旗": "Enclave", "昂科拉": "Encore",
    "迈锐宝": "Malibu", "迈锐宝XL": "Malibu XL",
    "科鲁兹": "Cruze", "赛欧": "Sail", "科迈罗": "Camaro",
    "探界者": "Equinox", "开拓者": "Blazer", "畅巡": "Menlo",
    "IQ锐歌": "Lyriq",
    # Toyota
    "凯美瑞": "Camry", "卡罗拉": "Corolla", "雷凌": "Levin",
    "亚洲龙": "Avalon", "汉兰达": "Highlander", "普拉多": "Prado",
    "兰德酷路泽": "Land Cruiser", "陆地巡洋舰": "Land Cruiser",
    "霸道": "Prado", "塞纳": "Sienna", "埃尔法": "Alphard",
    "威尔法": "Vellfire", "皇冠": "Crown", "锐志": "Mark X",
    "RAV4荣放": "RAV4", "威兰达": "Wildlander",
    "C-HR": "C-HR", "奕泽": "Izoa", "锋兰达": "Frontlander",
    "凌放": "Harrier", "致炫": "Yaris", "致享": "Yaris L",
    "卡罗拉锐放": "Corolla Cross", "卡罗拉双擎E+": "Corolla PHEV",
    "超霸": "4Runner", "超霸4Runner": "4Runner",
    # Honda
    "雅阁": "Accord", "思域": "Civic", "飞度": "Fit",
    "缤智": "Vezel", "皓影": "Breeze", "冠道": "Avancier",
    "型格": "Integra", "致在": "ZR-V", "奥德赛": "Odyssey",
    "艾力绅": "Elysion", "凌派": "Crider", "享域": "ENVIX",
    "思铭": "INSPIRE", "英诗派": "INSPIRE", "雅阁锐·混动": "Accord Hybrid",
    # Nissan
    "轩逸": "Sylphy", "天籁": "Teana", "奇骏": "X-Trail",
    "逍客": "Qashqai", "蓝鸟": "Sylphy Classic", "骐达": "Tiida",
    "楼兰": "Murano", "途乐": "Patrol", "贵士": "Quest",
    "途达": "Terra", "西玛": "Maxima", "劲客": "Kicks",
    "阳光": "Sunny", "骊威": "Livina",
    # Hyundai / Kia
    "伊兰特": "Elantra", "朗动": "Elantra Langdong",
    "领动": "Elantra Lingdong", "悦动": "Elantra Yuedong",
    "名图": "Mistra", "索纳塔": "Sonata", "途胜": "Tucson",
    "胜达": "Santa Fe", "ix35": "ix35", "ix25": "ix25",
    "瑞纳": "Verna", "雅尊": "Azera", "捷恩斯": "Genesis",
    "K2": "K2", "K3": "K3", "K4": "K4", "K5": "K5",
    "智跑": "Sportage", "狮跑": "Sportage", "极睿": "Niro",
    "嘉华": "Carnival", "佳乐": "Carens", "千里马": "Cerato",
    # Geely + GAC + Chery
    "帝豪": "Emgrand", "帝豪GL": "Emgrand GL", "帝豪EV": "Emgrand EV",
    "远景": "Vision", "博越": "Boyue", "博越L": "Boyue L",
    "博瑞": "Borui", "缤越": "Binyue", "缤瑞": "Binrui",
    "星瑞": "Preface", "星越": "Xingyue", "星越L": "Xingyue L",
    "星越S": "Xingyue S", "缤越Cool": "Binyue Cool",
    "嘉际": "Jiaji", "ICON": "Icon", "豪情": "Haoqing",
    "瑞虎3": "Tiggo 3", "瑞虎5": "Tiggo 5", "瑞虎7": "Tiggo 7",
    "瑞虎8": "Tiggo 8", "瑞虎9": "Tiggo 9", "艾瑞泽": "Arrizo",
    "小蚂蚁": "eQ1", "传祺M8": "Trumpchi M8", "影豹": "Empow",
    "影酷": "Empow", "GS3": "GS3", "GS4": "GS4", "GS8": "GS8",
    # BYD
    "秦": "Qin", "秦PLUS": "Qin PLUS", "秦Pro": "Qin Pro",
    "汉": "Han", "汉EV": "Han EV", "唐": "Tang", "唐DM": "Tang DM",
    "宋": "Song", "宋PLUS": "Song PLUS", "宋Pro": "Song Pro",
    "元": "Yuan", "元PLUS": "Yuan PLUS", "元新能源": "Yuan EV",
    "海豚": "Dolphin", "海豹": "Seal", "海鸥": "Seagull",
    "海狮": "Sealion", "海狮07": "Sealion 07",
    "驱逐舰05": "Destroyer 05", "护卫舰07": "Frigate 07",
    "F0": "F0", "F3": "F3", "速锐": "Surui", "e1": "e1",
    "e2": "e2", "e3": "e3",
    # Wuling / Baojun
    "宏光MINIEV": "Hongguang Mini EV", "宏光": "Hongguang",
    "宏光S": "Hongguang S", "宏光PLUS": "Hongguang Plus",
    "缤果": "Binggo", "缤果PLUS": "Binggo Plus",
    "星辰": "Xingchen", "凯捷": "Victory", "佳辰": "Jiachen",
    "Air ev": "Air EV", "悦也": "Yueye",
    # Roewe / MG
    "科莱威CLEVER": "Clever", "RX5新能源": "RX5 EV",
    "RX5": "RX5", "RX3": "RX3", "RX8": "RX8",
    "i5": "i5", "i6": "i6", "i6MAX": "i6 MAX",
    "ZS": "ZS", "HS": "HS", "ZS新能源": "ZS EV",
    # NIO / Onvo / Avita / Aito / Xpeng / Li / Zeekr / Xiaomi
    "ES6": "ES6", "ES7": "ES7", "ES8": "ES8", "EC6": "EC6",
    "ET5": "ET5", "ET7": "ET7", "ET9": "ET9",
    "乐道L60": "Onvo L60", "L60": "L60",
    "P5": "P5", "P7": "P7", "P7+": "P7+", "G3": "G3",
    "G6": "G6", "G9": "G9", "X9": "X9", "MONA": "MONA",
    "M5": "M5", "M7": "M7", "M9": "M9",
    "L6": "L6", "L7": "L7", "L8": "L8", "L9": "L9",
    "001": "001", "007": "007", "009": "009", "X": "X",
    "SU7": "SU7", "YU7": "YU7",
    # Hongqi
    "天工05": "Tiangong 05", "天工06": "Tiangong 06",
    "天工08": "Tiangong 08",
    "H5": "H5", "H7": "H7", "H9": "H9",
    "HS3": "HS3", "HS5": "HS5", "HS7": "HS7", "HQ9": "HQ9",
    "E-HS9": "E-HS9", "E-QM5": "E-QM5",
    # Voyah / Tank / Lynk & Co
    "知音": "Free", "梦想家": "Dreamer", "追光": "Zhuiguang",
    "Voyah 知音": "Free", "Voyah 梦想家": "Dreamer",
    "700": "Tank 700", "700新能源": "Tank 700 PHEV",
    "Tank 700新能源": "Tank 700 PHEV",
    "300": "Tank 300", "400": "Tank 400", "500": "Tank 500",
    "01": "01", "02": "02", "03": "03", "05": "05",
    "06": "06", "08": "08", "09": "09", "Z10": "Z10",
    # Ford
    "蒙迪欧": "Mondeo", "福克斯": "Focus", "翼虎": "Kuga",
    "锐界": "Edge", "锐界L": "Edge L", "锐际": "Escape",
    "探险者": "Explorer", "烈马": "Bronco", "领睿": "Equator Sport",
    "领裕": "Equator", "全顺": "Transit", "途睿欧": "Tourneo",
    "电马": "Mustang Mach-E", "福克斯Active": "Focus Active",
    "翼搏": "EcoSport", "嘉年华": "Fiesta", "金牛座": "Taurus",
    "锐界Plus": "Edge Plus", "Ford F-150猛禽": "F-150 Raptor",
    "猛禽": "F-150 Raptor", "F-150猛禽": "F-150 Raptor",
    # Land Rover / Bentley / Rolls / Maserati / Ferrari / Lambo
    "揽胜": "Range Rover", "揽胜运动": "Range Rover Sport",
    "揽胜极光": "Range Rover Evoque", "揽胜星脉": "Range Rover Velar",
    "极光": "Range Rover Evoque", "星脉": "Range Rover Velar",
    "发现": "Discovery", "发现运动": "Discovery Sport",
    "卫士": "Defender", "神行者": "Freelander",
    "Land Rover 运动": "Range Rover Sport",
    "Land Rover 极光": "Range Rover Evoque",
    "飞驰": "Flying Spur", "添越": "Bentayga",
    "添越插电混动": "Bentayga Hybrid", "欧陆": "Continental",
    "慕尚": "Mulsanne", "雅致": "Arnage",
    "Bentley 飞驰": "Flying Spur",
    "库里南": "Cullinan", "古思特": "Ghost", "幻影": "Phantom",
    "曜影": "Dawn", "魅影": "Wraith", "银影": "Silver Shadow",
    "总裁": "Quattroporte", "莱万特": "Levante", "吉博力": "Ghibli",
    "Maserati 总裁": "Quattroporte", "Maserati 莱万特": "Levante",
    # Lincoln
    "航海家": "Nautilus", "飞行家": "Aviator", "大陆": "Continental",
    "冒险家": "Corsair", "领航员": "Navigator", "MKZ": "MKZ",
    "MKC": "MKC", "MKX": "MKX",
    # Lexus / Infiniti / Acura
    "UX新能源": "UX EV", "ES混动": "ES Hybrid",
    "QX50": "QX50", "QX55": "QX55", "QX60": "QX60",
    "RDX": "RDX", "CDX": "CDX",
    # Mercedes / BMW / Audi (often have CN-specific patterns)
    "A ClassAMG进口": "A-Class AMG",
    "E Class新能源": "E-Class PHEV",
    "C ClassAMG": "C-Class AMG",
    "Audi A6进口": "A6", "BMW X2进口": "X2",
    "Audi SQ7": "SQ7", "BMW X4": "X4",
    # Alfa / Mazda / others
    "Giulia朱丽叶": "Giulia", "朱丽叶": "Giulia",
    "斯泰尔维奥": "Stelvio",
    "阿特兹": "Atenza", "昂克赛拉": "Axela", "CX-50行也": "CX-50",
    # Changan / JAC / Dongfeng / Brilliance
    "奔奔": "Benben", "奔奔E-Star": "Benben E-Star",
    "逸动": "Eado", "逸动PLUS": "Eado PLUS", "逸动DT": "Eado DT",
    "悦翔": "Yuexiang", "锐程": "Raeton", "CS35": "CS35",
    "CS55": "CS55", "CS75": "CS75", "CS95": "CS95",
    "UNI-T": "UNI-T", "UNI-V": "UNI-V", "UNI-K": "UNI-K",
    "钇为": "Yiwei", "钇为3": "Yiwei 3",
    "瑞风": "Refine", "嘉悦": "Sehol",
    "奕炫": "Aeolus E70", "帕拉索": "Palasso",
    "AX7": "AX7", "AX4": "AX4",
    # Iconic imports
    "英力士掷弹兵": "Ineos Grenadier", "掷弹兵": "Grenadier",
    # Misc CN brand model-as-name (newer EVs)
    "尊界S800": "Maextro S800",
    "智界S7": "Luxeed S7", "智界R7": "Luxeed R7",
    "享界S9": "Stelato S9",
    # Mercedes-Benz commercial / AMG / Lambo / Ferrari / Misc that lack series above
    "威霆": "Vito", "唯雅诺": "Viano", "凌特": "Sprinter",
    "AMG": "AMG", "AMG GT": "AMG GT",
    "Huracán": "Huracán", "Urus": "Urus",
    "Revuelto": "Revuelto", "Aventador": "Aventador",
    "GTC4Lusso": "GTC4Lusso", "Portofino": "Portofino",
    "Purosangue": "Purosangue", "SF90": "SF90", "SF90XX": "SF90 XX",
    "Roma": "Roma", "F8": "F8", "296": "296", "812": "812",
    "Evora": "Evora", "Elise": "Elise", "Eletre": "Eletre",
    "Emira": "Emira", "Emeya": "Emeya",
    "Mustang": "Mustang",
    "HIACE": "HiAce", "SIENNA": "Sienna", "SUPRA": "Supra",
    "HUMMER": "Hummer",
    "Ghibli": "Ghibli",
    # Micro-EV / niche city EVs
    "熊猫mini": "Panda Mini", "花仙子": "Hongguang Flower Fairy",
    "花仙子款": "Hongguang Flower Fairy",
    "黑猫": "Ora Black Cat", "白猫": "Ora White Cat",
    "小马": "Pony EV", "小虎EV": "Xiaohu EV",
    "QQ冰淇淋": "QQ Ice Cream", "纳米EX1": "Nano Box EX1",
    "阿尔法T": "Alpha T", "阿尔法S": "Alpha S", "阿尔法T(ARCFOX": "Alpha T",
    "风光MINI EV": "Fengguang Mini EV",
    "赛那SIENNA": "Sienna",
    "迈腾GTE PHEV": "Magotan GTE PHEV", "迈腾GTE": "Magotan GTE",
    "ARIYA艾睿雅": "Ariya", "艾睿雅": "Ariya",
    "E萤火虫": "Firefly", "萤火虫": "Firefly",
    "FOR-Four乖乖虎": "ForFour",
    "蓝气球": "Blue Balloon", "至境世家": "Galaxy Family",
    # New CN long-wheelbase / EVs / imports / mass-market
    "唐L": "Tang L", "汉L": "Han L",
    "揽境": "Talagon", "揽巡": "Tavendor",
    "朗逸纯电": "Lavida EV", "迈腾纯电": "Magotan EV",
    "红杉": "Sequoia", "英仕派": "Inspire",
    "纳米": "Nano", "纳米06": "Nano 06",
    "星海T5": "Starhai T5", "星海L7": "Starhai L7",
    "IQ傲歌": "Optiq",
    # Aston Martin V models, Ford CN names, niche RV
    "V8 Vantage": "V8 Vantage", "V12 Vantage": "V12 Vantage",
    "DB11": "DB11", "DB12": "DB12", "DBX": "DBX",
    "游骑侠Ranger": "Ranger", "游骑侠": "Ranger",
    "沃森威尔1917宿营车": "Watson-Will 1917 Camper",
    "沃森威尔福特黑武士": "Watson-Will Ford Dark Warrior",
    # Niche / EVs / coupes / tunings / market-mods
    "运动": "Range Rover Sport", "电动MINI": "MINI Electric",
    "纯电GV70": "Electrified GV70",
    "XC60插电式混动": "XC60 PHEV",
    "GLC轿跑": "GLC Coupe", "宏光V": "Hongguang V",
    "大切诺基": "Grand Cherokee", "大切诺基4xe": "Grand Cherokee 4xe",
    "兰德酷路泽(进口)LC76": "Land Cruiser LC76",
    "依维柯NewDaily房车": "NewDaily Camper",
    "勇士·战斧": "Warrior Tomahawk",
    "泰山": "Tai Shan",
    # — additions for the leftover CJK rows the normalizer didn't catch —
    # Geely Galaxy: Xingyuan compact EV
    "星愿": "Galaxy Xingyuan",
    # Honda China sub-brands (Everus + GAC Honda new energy)
    "本田M-NV": "M-NV", "本田X-NV": "X-NV",
    "四驱长续航Max": "AWD Long Range Max",  # complectation leak, lift to model
    "猎光e:NS2": "e:NS2",
    # Hyundai
    "库斯途": "Custo",
    # Onvo (NIO sub-brand)
    "乐道L90": "L90",
    # Geely Forthing / Dongfeng Fengxing
    "风行T5": "Forthing T5",
    # Foton SAIC mini-truck/van
    "小海狮X30": "Mini Sea Lion X30",
    # World Hightech Auto (世极)
    "世极": "Shiji",
    # Mitsubishi
    "欧蓝德": "Outlander",
    # Volkswagen China
    "途观L": "Tiguan L",
    # Maserati
    "Grecale格雷嘉": "Grecale",
    # Bentley
    "飞驰插电混动": "Flying Spur PHEV", "飞驰插电式混动": "Flying Spur PHEV",
    # BYD Tang series suffixes
    "唐新能源": "Tang EV",
    # Exeed
    "凌云": "Lingyun",
    # Ora (Great Wall)
    "好猫": "Funky Cat",
    # Baojun
    "云朵": "Yunduo", "悦也Plus": "Yueye Plus",
    # Farizon
    "星享V6E": "Xingxiang V6E",
    # Roewe
    "i6经典": "i6 Classic",
    # Skoda
    "柯珞克": "Karoq",
    # JMC
    "集团新能源": "Group EV", "集团 EV": "Group EV",
    # Volvo PHEV variants (clean leak)
    "S90插电式混动": "S90 PHEV", "XC70插电式混动": "XC70 PHEV",
    # Generic ничего-не-говорящий "新能源" leaked as series — leave un-translated
    # so frontend treats it as missing model
}

# SERIES_TO_BRAND — model-as-brand fallback for CN sources where the listing
# omits the manufacturer prefix (very common on che168 for premium models).
# Lookup: when BRAND_MAP doesn't match the first carname token, try here.
# Keep keys identical to SERIES_MAP keys so the model itself still translates.
SERIES_TO_BRAND = {
    # Mercedes-Benz commercial / AMG / Maybach
    "威霆": "Mercedes-Benz", "唯雅诺": "Mercedes-Benz", "凌特": "Mercedes-Benz",
    "AMG": "Mercedes-AMG", "AMG GT": "Mercedes-AMG",
    # Bentley
    "飞驰": "Bentley", "添越": "Bentley", "添越插电混动": "Bentley",
    "欧陆": "Bentley", "慕尚": "Bentley", "雅致": "Bentley",
    # Rolls-Royce
    "库里南": "Rolls-Royce", "古思特": "Rolls-Royce", "幻影": "Rolls-Royce",
    "曜影": "Rolls-Royce", "魅影": "Rolls-Royce", "银影": "Rolls-Royce",
    # Lamborghini
    "Huracán": "Lamborghini", "Urus": "Lamborghini",
    "Revuelto": "Lamborghini", "Aventador": "Lamborghini",
    # Ferrari
    "GTC4Lusso": "Ferrari", "Portofino": "Ferrari", "Purosangue": "Ferrari",
    "SF90": "Ferrari", "SF90XX": "Ferrari", "Roma": "Ferrari",
    "F8": "Ferrari", "296": "Ferrari", "812": "Ferrari",
    # Toyota
    "凯美瑞": "Toyota", "卡罗拉": "Toyota", "雷凌": "Toyota",
    "亚洲龙": "Toyota", "汉兰达": "Toyota", "普拉多": "Toyota",
    "兰德酷路泽": "Toyota", "陆地巡洋舰": "Toyota", "霸道": "Toyota",
    "塞纳": "Toyota", "埃尔法": "Toyota", "威尔法": "Toyota",
    "皇冠": "Toyota", "锐志": "Toyota", "RAV4荣放": "Toyota",
    "威兰达": "Toyota", "C-HR": "Toyota", "奕泽": "Toyota",
    "锋兰达": "Toyota", "凌放": "Toyota", "致炫": "Toyota", "致享": "Toyota",
    "卡罗拉锐放": "Toyota", "卡罗拉双擎E+": "Toyota",
    "超霸": "Toyota", "超霸4Runner": "Toyota",
    "SUPRA": "Toyota", "HIACE": "Toyota", "SIENNA": "Toyota",
    # Honda
    "雅阁": "Honda", "思域": "Honda", "飞度": "Honda",
    "缤智": "Honda", "皓影": "Honda", "冠道": "Honda",
    "型格": "Honda", "致在": "Honda", "奥德赛": "Honda",
    "艾力绅": "Honda", "凌派": "Honda", "享域": "Honda",
    "思铭": "Honda", "英诗派": "Honda",
    # Nissan
    "轩逸": "Nissan", "天籁": "Nissan", "奇骏": "Nissan",
    "逍客": "Nissan", "蓝鸟": "Nissan", "骐达": "Nissan",
    "楼兰": "Nissan", "途乐": "Nissan", "贵士": "Nissan",
    "途达": "Nissan", "西玛": "Nissan", "劲客": "Nissan",
    "阳光": "Nissan", "骊威": "Nissan",
    # VW
    "朗逸": "Volkswagen", "帕萨特": "Volkswagen", "凌渡": "Volkswagen",
    "探岳": "Volkswagen", "探岳X": "Volkswagen", "途岳": "Volkswagen",
    "途昂": "Volkswagen", "途昂X": "Volkswagen", "途观": "Volkswagen",
    "途锐": "Volkswagen", "途铠": "Volkswagen", "威然": "Volkswagen",
    "桑塔纳": "Volkswagen", "宝来": "Volkswagen", "高尔夫": "Volkswagen",
    "速腾": "Volkswagen", "迈腾": "Volkswagen", "辉昂": "Volkswagen",
    "辉腾": "Volkswagen", "蔚揽": "Volkswagen", "夏朗": "Volkswagen",
    "昕动": "Volkswagen", "电动MINI": "MINI",
    # Buick / Chevy / Cadillac
    "英朗": "Buick", "威朗": "Buick", "威朗Pro": "Buick",
    "君越": "Buick", "君威": "Buick", "凯越": "Buick", "世纪": "Buick",
    "微蓝6": "Buick", "微蓝7": "Buick",
    "昂科威": "Buick", "昂科威Plus": "Buick",
    "昂科旗": "Buick", "昂科拉": "Buick",
    "迈锐宝": "Chevrolet", "迈锐宝XL": "Chevrolet",
    "科鲁兹": "Chevrolet", "赛欧": "Chevrolet", "科迈罗": "Chevrolet",
    "探界者": "Chevrolet", "开拓者": "Chevrolet", "畅巡": "Chevrolet",
    "IQ锐歌": "Cadillac",
    # Hyundai/Kia
    "伊兰特": "Hyundai", "朗动": "Hyundai", "领动": "Hyundai", "悦动": "Hyundai",
    "名图": "Hyundai", "索纳塔": "Hyundai", "途胜": "Hyundai", "胜达": "Hyundai",
    "ix35": "Hyundai", "ix25": "Hyundai", "瑞纳": "Hyundai", "雅尊": "Hyundai",
    "智跑": "Kia", "狮跑": "Kia", "极睿": "Kia",
    "嘉华": "Kia", "佳乐": "Kia", "千里马": "Kia",
    # Geely / Chery / BYD / Wuling
    "帝豪": "Geely", "帝豪GL": "Geely", "帝豪EV": "Geely",
    "远景": "Geely", "博越": "Geely", "博越L": "Geely",
    "博瑞": "Geely", "缤越": "Geely", "缤瑞": "Geely",
    "星瑞": "Geely", "星越": "Geely", "星越L": "Geely",
    "星越S": "Geely", "嘉际": "Geely",
    "瑞虎3": "Chery", "瑞虎5": "Chery", "瑞虎7": "Chery",
    "瑞虎8": "Chery", "瑞虎9": "Chery", "艾瑞泽": "Chery",
    "小蚂蚁": "Chery", "影豹": "GAC Trumpchi", "影酷": "GAC Trumpchi",
    "传祺M8": "GAC Trumpchi",
    "秦": "BYD", "秦PLUS": "BYD", "秦Pro": "BYD",
    "汉": "BYD", "汉EV": "BYD", "唐": "BYD", "唐DM": "BYD",
    "宋": "BYD", "宋PLUS": "BYD", "宋Pro": "BYD",
    "元": "BYD", "元PLUS": "BYD", "元新能源": "BYD",
    "海豚": "BYD", "海豹": "BYD", "海鸥": "BYD",
    "海狮": "BYD", "海狮07": "BYD",
    "驱逐舰05": "BYD", "护卫舰07": "BYD",
    "宏光MINIEV": "Wuling", "宏光": "Wuling", "宏光S": "Wuling",
    "宏光PLUS": "Wuling", "缤果": "Wuling", "缤果PLUS": "Wuling",
    "星辰": "Wuling", "凯捷": "Wuling", "佳辰": "Wuling",
    "悦也": "Wuling", "Air ev": "Wuling",
    # Roewe / MG
    "科莱威CLEVER": "Roewe", "RX5新能源": "Roewe", "RX5": "Roewe",
    "RX3": "Roewe", "RX8": "Roewe", "i5": "Roewe", "i6": "Roewe",
    "i6MAX": "Roewe", "ZS新能源": "MG", "ZS": "MG", "HS": "MG",
    # NIO / Onvo / Xpeng / Li / Zeekr / AITO / Xiaomi
    "ES6": "NIO", "ES7": "NIO", "ES8": "NIO", "EC6": "NIO",
    "ET5": "NIO", "ET7": "NIO", "ET9": "NIO",
    "乐道L60": "Onvo", "L60": "Onvo",
    "P5": "XPeng", "P7": "XPeng", "P7+": "XPeng",
    "G3": "XPeng", "G6": "XPeng", "G9": "XPeng",
    "X9": "XPeng", "MONA": "XPeng",
    "M5": "AITO", "M7": "AITO", "M9": "AITO",
    "L6": "Li Auto", "L7": "Li Auto", "L8": "Li Auto", "L9": "Li Auto",
    "001": "Zeekr", "007": "Zeekr", "009": "Zeekr", "X": "Zeekr",
    "SU7": "Xiaomi", "YU7": "Xiaomi",
    # Hongqi
    "天工05": "Hongqi", "天工06": "Hongqi", "天工08": "Hongqi",
    "H5": "Hongqi", "H7": "Hongqi", "H9": "Hongqi",
    "HS3": "Hongqi", "HS5": "Hongqi", "HS7": "Hongqi",
    "HQ9": "Hongqi", "E-HS9": "Hongqi", "E-QM5": "Hongqi",
    # Voyah / Tank / Lynk
    "知音": "Voyah", "梦想家": "Voyah", "追光": "Voyah",
    "700新能源": "Tank", "300": "Tank", "400": "Tank", "500": "Tank",
    "01": "Lynk & Co", "02": "Lynk & Co", "03": "Lynk & Co",
    "05": "Lynk & Co", "06": "Lynk & Co", "08": "Lynk & Co",
    "09": "Lynk & Co", "Z10": "Lynk & Co",
    # Ford / Lincoln
    "蒙迪欧": "Ford", "福克斯": "Ford", "翼虎": "Ford",
    "锐界": "Ford", "锐界L": "Ford", "锐际": "Ford",
    "探险者": "Ford", "烈马": "Ford", "领睿": "Ford",
    "领裕": "Ford", "全顺": "Ford", "途睿欧": "Ford",
    "电马": "Ford", "福克斯Active": "Ford", "翼搏": "Ford",
    "嘉年华": "Ford", "金牛座": "Ford", "猛禽": "Ford",
    "F-150猛禽": "Ford", "Mustang": "Ford",
    "航海家": "Lincoln", "飞行家": "Lincoln", "大陆": "Lincoln",
    "冒险家": "Lincoln", "领航员": "Lincoln",
    "MKZ": "Lincoln", "MKC": "Lincoln", "MKX": "Lincoln",
    # Land Rover
    "揽胜": "Land Rover", "揽胜运动": "Land Rover",
    "揽胜极光": "Land Rover", "揽胜星脉": "Land Rover",
    "极光": "Land Rover", "星脉": "Land Rover",
    "发现": "Land Rover", "发现运动": "Land Rover",
    "卫士": "Land Rover", "神行者": "Land Rover",
    # Maserati
    "总裁": "Maserati", "莱万特": "Maserati", "吉博力": "Maserati",
    "Ghibli": "Maserati",
    # Alfa / Mazda / Lotus / Misc
    "Giulia朱丽叶": "Alfa Romeo", "朱丽叶": "Alfa Romeo",
    "斯泰尔维奥": "Alfa Romeo",
    "阿特兹": "Mazda", "昂克赛拉": "Mazda", "CX-50行也": "Mazda",
    "Evora": "Lotus", "Elise": "Lotus", "Eletre": "Lotus",
    "Emira": "Lotus", "Emeya": "Lotus", "EMEYA": "Lotus",
    # — additions to recover the 12 mark-less rows —
    "唐新能源": "BYD",
    "库斯途": "Hyundai",
    "飞驰插电混动": "Bentley", "飞驰插电式混动": "Bentley",
    "Grecale格雷嘉": "Maserati",
    "途观L": "Volkswagen",
    "NewDaily房车": "Iveco",
    "乐道L90": "Onvo",
    "风行T5": "Geely Forthing",
    "小海狮X30": "Foton",
    "世极": "Shiji",  # niche Chinese EV brand
    "欧蓝德": "Mitsubishi",
    "HUMMER": "Hummer", "悍马": "Hummer",
    # Changan / JAC / Dongfeng / Brilliance / Aion
    "奔奔": "Changan", "奔奔E-Star": "Changan",
    "逸动": "Changan", "逸动PLUS": "Changan", "逸动DT": "Changan",
    "悦翔": "Changan", "锐程": "Changan",
    "CS35": "Changan", "CS55": "Changan", "CS75": "Changan", "CS95": "Changan",
    "UNI-T": "Changan", "UNI-V": "Changan", "UNI-K": "Changan",
    "钇为": "JAC", "钇为3": "JAC", "瑞风": "JAC", "嘉悦": "JAC",
    "奕炫": "Dongfeng Aeolus", "帕拉索": "Dongfeng",
    "AX7": "Dongfeng", "AX4": "Dongfeng",
    "AION S": "Aion", "AION Y": "Aion", "AION V": "Aion", "AION LX": "Aion",
    # Iconic
    "英力士掷弹兵": "Ineos", "掷弹兵": "Ineos",
    # New CN luxe brands
    "尊界S800": "Maextro",
    "智界S7": "Luxeed", "智界R7": "Luxeed",
    "享界S9": "Stelato",
    # Niche / EVs / coupes / market-mods
    "运动": "Land Rover", "电动MINI": "MINI",
    "纯电GV70": "Genesis", "XC60插电式混动": "Volvo",
    "GLC轿跑": "Mercedes-Benz", "宏光V": "Wuling",
    "大切诺基": "Jeep", "大切诺基4xe": "Jeep",
    "兰德酷路泽(进口)LC76": "Toyota",
    "依维柯NewDaily房车": "Iveco",
    "勇士·战斧": "BAW", "泰山": "Tank",
    "Lorinser": "Lorinser", "LUMMA": "LUMMA",
    # Micro-EV crossover (carname often without parent brand)
    "熊猫mini": "Geely", "花仙子": "Geely", "花仙子款": "Geely",
    "黑猫": "GWM Ora", "白猫": "GWM Ora",
    "小马": "Pony", "小虎EV": "Pony",
    "QQ冰淇淋": "Chery", "纳米EX1": "Dongfeng",
    "阿尔法T": "ARCFOX", "阿尔法S": "ARCFOX", "阿尔法T(ARCFOX": "ARCFOX",
    "风光MINI EV": "Dongfeng Fengguang",
    "赛那SIENNA": "Toyota",
    "迈腾GTE PHEV": "Volkswagen", "迈腾GTE": "Volkswagen",
    "ARIYA艾睿雅": "Nissan", "艾睿雅": "Nissan",
    "E萤火虫": "NIO", "萤火虫": "NIO",
    "FOR-Four乖乖虎": "Smart",
    "蓝气球": "Smart",  # Smart Blue Balloon special edition
    "至境世家": "Geely",  # Geely Galaxy
    "唐L": "BYD", "汉L": "BYD",
    "揽境": "Volkswagen", "揽巡": "Volkswagen",
    "朗逸纯电": "Volkswagen", "迈腾纯电": "Volkswagen",
    "红杉": "Toyota", "英仕派": "Honda",
    "纳米": "Dongfeng", "纳米06": "Dongfeng",
    "星海T5": "Starhai", "星海L7": "Starhai",
    "IQ傲歌": "Cadillac",
    "V8 Vantage": "Aston Martin", "V12 Vantage": "Aston Martin",
    "DB11": "Aston Martin", "DB12": "Aston Martin", "DBX": "Aston Martin",
    "游骑侠Ranger": "Ford", "游骑侠": "Ford",
    "沃森威尔1917宿营车": "Watson-Will", "沃森威尔福特黑武士": "Watson-Will",
}

# Strip these suffix tags from extracted series before SERIES_MAP lookup.
SERIES_SUFFIX_NOISE = (
    "新能源", "进口", "插电混动", "插电式混合动力", "混动", "PHEV", "EV",
)


COLOR_MAP = {
    "白色": "White", "黑色": "Black", "银色": "Silver", "灰色": "Gray",
    "深灰色": "Dark Gray", "银灰色": "Silver Gray", "浅灰色": "Light Gray",
    "蓝色": "Blue", "深蓝色": "Dark Blue", "浅蓝色": "Light Blue",
    "红色": "Red", "深红色": "Dark Red", "暗红色": "Dark Red",
    "棕色": "Brown", "咖啡色": "Brown",
    "橙色": "Orange", "黄色": "Yellow", "绿色": "Green",
    "紫色": "Purple", "香槟色": "Champagne", "金色": "Gold", "粉色": "Pink",
    "米色": "Beige", "其他": "Other", "其它": "Other",
}

FUEL_MAP = {
    "汽油": "Petrol", "柴油": "Diesel", "电动": "Electric", "纯电": "Electric",
    "纯电动": "Electric",
    "混合动力": "Hybrid", "油电混合": "Hybrid", "插电混动": "PHEV",
    "插电式混合动力": "PHEV", "增程式": "EREV", "增程": "EREV",
    # Synonyms for series-hybrid that arrive already Latin-encoded from
    # some sources (e.g. autocango). REEV ("Range-Extended EV") is the
    # same physical configuration as EREV — engine acts as generator only,
    # wheels driven by motor. Customs-wise this matters: in KZ from
    # Jan 2026 EREV pays 0% duty, classic HEV/PHEV pays full ~15%.
    "REEV": "EREV", "Reev": "EREV", "EREV": "EREV",
    "氢燃料": "Hydrogen", "天然气": "CNG",
}

TRANSMISSION_MAP = {
    "手动": "Manual", "自动": "Automatic", "无级变速": "CVT",
    "双离合": "DCT", "湿式双离合": "Wet DCT", "干式双离合": "Dry DCT",
    "AMT": "AMT", "电动单速变速箱": "Single-Speed", "电动": "Single-Speed",
}

DRIVE_MAP = {
    "前置前驱": "FWD", "前驱": "FWD",
    "前置后驱": "RWD", "后置后驱": "RWD", "中置后驱": "RWD", "后驱": "RWD",
    "全时四驱": "AWD", "适时四驱": "AWD", "分时四驱": "AWD", "四驱": "AWD",
    "前置四驱": "AWD", "中置四驱": "AWD", "后置四驱": "AWD",
    "双电机四驱": "AWD", "三电机四驱": "AWD", "四电机四驱": "AWD",
}

CITY_MAP = {
    "北京": "Beijing", "上海": "Shanghai", "广州": "Guangzhou", "深圳": "Shenzhen",
    "杭州": "Hangzhou", "成都": "Chengdu", "重庆": "Chongqing", "南京": "Nanjing",
    "武汉": "Wuhan", "西安": "Xi'an", "天津": "Tianjin", "苏州": "Suzhou",
    "青岛": "Qingdao", "沈阳": "Shenyang", "济南": "Jinan", "哈尔滨": "Harbin",
    "长春": "Changchun", "合肥": "Hefei", "贵阳": "Guiyang", "烟台": "Yantai",
    "宁波": "Ningbo", "郑州": "Zhengzhou", "南宁": "Nanning", "昆明": "Kunming",
    "潍坊": "Weifang", "东莞": "Dongguan", "温州": "Wenzhou", "淄博": "Zibo",
    "威海": "Weihai", "乌鲁木齐": "Urumqi", "南昌": "Nanchang", "厦门": "Xiamen",
    "福州": "Fuzhou", "石家庄": "Shijiazhuang", "太原": "Taiyuan", "兰州": "Lanzhou",
    "大连": "Dalian", "佛山": "Foshan", "无锡": "Wuxi", "长沙": "Changsha",
}
