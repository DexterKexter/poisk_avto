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
    "埃安": "Aion", "广汽埃安": "Aion",
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

COLOR_MAP = {
    "白色": "White", "黑色": "Black", "银色": "Silver", "灰色": "Gray",
    "深灰色": "Dark Gray", "银灰色": "Silver Gray", "浅灰色": "Light Gray",
    "蓝色": "Blue", "深蓝色": "Dark Blue", "浅蓝色": "Light Blue",
    "红色": "Red", "深红色": "Dark Red", "暗红色": "Dark Red",
    "棕色": "Brown", "咖啡色": "Brown",
    "橙色": "Orange", "黄色": "Yellow", "绿色": "Green",
    "紫色": "Purple", "香槟色": "Champagne", "金色": "Gold", "粉色": "Pink",
    "米色": "Beige", "其他": "Other",
}

FUEL_MAP = {
    "汽油": "Petrol", "柴油": "Diesel", "电动": "Electric", "纯电": "Electric",
    "纯电动": "Electric",
    "混合动力": "Hybrid", "油电混合": "Hybrid", "插电混动": "PHEV",
    "插电式混合动力": "PHEV", "增程式": "EREV", "增程": "EREV",
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
