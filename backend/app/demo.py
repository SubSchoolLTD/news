"""Clearly labelled synthetic scenarios, isolated in each visitor's own workspace."""
from datetime import datetime, timedelta, timezone

from .db import Item, Job, Member, Workspace, now, pack, record
from .research import retrieve_bank


def seed_demo(db, user, variant="industrial"):
    edu = variant == "subschool"
    profile = {
        "name": "SubSchool" if edu else "Volga Industrial Group",
        "website": "https://subschool.us" if edu else "https://example.com",
        "industry": "Education technology / SaaS" if edu else "Industrial manufacturing / steel products",
        "description": {"en": "An online platform for teachers and schools, with subscriptions and digital learning tools." if edu else "A large manufacturer of steel components supplying industrial clients and exporting part of its production.", "ru": "Онлайн-платформа для преподавателей и школ: подписки и цифровые инструменты обучения." if edu else "Крупный производитель стальных компонентов для промышленных клиентов с экспортом части продукции."},
        "activities": ["Online teaching", "Subscription software", "AI learning tools"] if edu else ["Steel manufacturing", "Industrial supply", "Exports"],
        "regions": ["US", "Russia"],
        "scale": "Synthetic scenario; not disclosed" if edu else "Synthetic large enterprise (> RUB 15bn annual revenue)",
        "revenue": "Not disclosed" if edu else "Scenario band: > RUB 15bn",
        "market_position": "Not verified",
        "counterparties": ["Cloud infrastructure vendors", "Schools"] if edu else ["Industrial buyers", "Raw-material suppliers", "Logistics partners"],
        "competitors": [],
        "exposures": ["USD cloud infrastructure costs", "Russian household education budgets", "Teacher compensation", "Personal data regulation"] if edu else ["Floating-rate debt", "Export revenue in foreign currency", "Imported equipment", "Steel and energy input costs", "Investment programme"],
        "priorities": ["Subscription retention", "Sustainable AI unit economics", "School partnerships"] if edu else ["Protect operating margin", "Control financing costs", "Maintain supply continuity"],
        "keywords": ["education technology", "teacher wages", "AI inference costs", "data privacy"] if edu else ["steel prices", "Bank of Russia interest rate", "industrial exports", "energy costs"],
        "reviewed": True, "status": "confirmed", "version": 1,
        "unknowns": ["Actual cash-flow sensitivity and contract terms", "Company financials have not been verified"],
        "evidence": [{"title": "Synthetic demonstration profile", "url": "", "accessed_at": now()}],
    }
    ws = Workspace(name=profile["name"], profile=profile, settings={"keywords": profile["keywords"], "auto_monitor": False, "interval_minutes": 360, "alert_threshold": 80, "min_relevance": 20, "lookback_days": 30, "scheduled_briefs": []}, onboarded=True, demo=True)
    db.add(ws);db.flush()
    db.add(Member(workspace_id=ws.id, user_id=user.id, role="owner", decision_role="ceo"))
    examples = [
        (0, "risk", "macro", 94,
         "Financing costs stay in focus", "Стоимость финансирования остаётся в фокусе",
         "A simulated central-bank update keeps monetary policy restrictive.", "Учебное обновление центрального банка сохраняет жёсткие денежные условия.",
         "Your subscription customers may defer discretionary spending while teacher compensation stays sticky." if edu else "Your floating-rate debt and investment programme expose cash flow to a prolonged period of high financing costs.",
         "Клиенты могут откладывать расходы на подписки, пока оплата преподавателей остаётся высокой." if edu else "Долг с плавающей ставкой и инвестиционная программа делают денежный поток чувствительным к длительной дороговизне финансирования.",
         "If household budgets tighten and acquisition costs remain stable, retention becomes more valuable than broad discounting. Segment renewal risk before changing prices." if edu else "If borrowing costs remain elevated while input prices rise, investment headroom could narrow. Compare refinancing dates with project cash flows before committing to new capex.",
         "Если бюджеты семей сократятся при прежней стоимости привлечения, удержание клиентов станет важнее общих скидок. Перед изменением цен выделите сегменты риска продления." if edu else "Если стоимость заимствований останется высокой, а сырьё подорожает, возможности для инвестиций сузятся. Сопоставьте сроки рефинансирования и потоки проектов до новых капитальных затрат.",
         "Finance · This week: model retention and cash runway under a slower-renewal scenario." if edu else "Treasury · This week: map floating-rate exposure and refinancing dates; compare two financing scenarios.",
         "Финансы · На этой неделе: оценить удержание и запас ликвидности при замедлении продлений." if edu else "Казначейство · На этой неделе: сверить плавающие ставки и сроки рефинансирования, сравнить два сценария финансирования."),
        (0, "opportunity", "technology" if edu else "supply_chain", 89,
         "A window to improve unit economics" if edu else "A chance to diversify supply", "Возможность улучшить юнит-экономику" if edu else "Возможность диверсифицировать поставки",
         "A simulated supplier announces a new lower-cost service tier." if edu else "A simulated regional supplier opens additional production capacity.",
         "Учебный поставщик объявляет новый более доступный тариф." if edu else "Учебный региональный поставщик открывает дополнительные производственные мощности.",
         "Cloud infrastructure costs are part of your stated operating exposures." if edu else "Raw-material suppliers and supply continuity are part of your confirmed business context.",
         "Облачные расходы входят в указанные вами операционные риски." if edu else "Поставщики сырья и непрерывность снабжения входят в подтверждённый контекст бизнеса.",
         "A cheaper tier could help margins if its quality and latency meet teaching needs. Test a small cohort before migrating workloads; capacity and privacy terms remain unverified." if edu else "Extra capacity could reduce dependence on a single counterparty if quality and delivered costs are competitive. Qualification and logistics costs may offset the headline price advantage.",
         "Доступный тариф может улучшить маржу, если качество и задержка подходят для уроков. Проверьте его на небольшой группе до миграции; лимиты и условия обработки данных ещё неизвестны." if edu else "Новые мощности могут снизить зависимость от контрагента при сопоставимом качестве и полной стоимости. Квалификация и доставка могут поглотить преимущество цены.",
         "Engineering · Within 7 days: benchmark quality, latency and cost on a representative lesson set." if edu else "Procurement · Within 7 days: request a trial batch and compare landed cost and delivery reliability.",
         "Разработка · За 7 дней: сравнить качество, задержку и стоимость на типовых уроках." if edu else "Закупки · За 7 дней: запросить пробную партию и сравнить полную стоимость и надёжность доставки."),
        (2, "risk", "regulation", 86, "Data rules need an operational owner", "Требованиям к данным нужен ответственный",
         "A simulated draft introduces additional requirements for personal data processing.", "Учебный проект регулирования вводит дополнительные требования к обработке персональных данных.",
         "Your digital products process customer and employee data.", "Цифровые продукты компании обрабатывают данные клиентов и сотрудников.",
         "If adopted, the draft could require changes to vendor contracts and retention rules. A proposal is not an enacted obligation; confirm jurisdiction and dates before budgeting a rollout.",
         "В случае принятия могут потребоваться изменения договоров с подрядчиками и сроков хранения. Проект ещё не является обязательством: уточните юрисдикцию и даты до планирования внедрения.",
         "Legal · This week: map affected data flows and confirm the draft's legislative stage.", "Юристы · На этой неделе: описать затронутые потоки данных и уточнить стадию законопроекта."),
        (4, "mixed", "markets", 81, "Currency moves affect both sides of the margin", "Валюта влияет на обе стороны маржи",
         "A simulated currency update highlights increased exchange-rate volatility.", "Учебное обновление валютного рынка указывает на рост волатильности курса.",
         "USD infrastructure invoices and local-currency subscriptions create a currency mismatch." if edu else "Export revenue and imported equipment create two opposing currency exposures.",
         "Долларовые счета за инфраструктуру и подписки в местной валюте создают валютное несоответствие." if edu else "Экспортная выручка и импортное оборудование создают противоположные валютные риски.",
         "A weaker local currency could lift foreign-cost invoices before prices can be adjusted. Match cash receipts to payment dates; do not assume revenue naturally offsets costs." if edu else "Currency weakness may support export receipts while raising equipment costs. The net effect depends on timing, invoice currencies and existing contracts rather than the exchange rate alone.",
         "Ослабление местной валюты может увеличить внешние расходы раньше пересмотра цен. Сопоставьте поступления и даты платежей: автоматическая компенсация выручкой не подтверждена." if edu else "Ослабление валюты может поддержать экспортные поступления и удорожить оборудование. Итог зависит от сроков, валюты расчётов и контрактов, а не только от курса.",
         "Treasury · Next 48 hours: compare currency cash inflows and outflows by maturity.", "Казначейство · За 48 часов: сопоставить валютные поступления и платежи по срокам."),
        (6, "risk", "macro", 78, "Wage pressure can outlast slower demand", "Давление зарплат может пережить замедление спроса",
         "A simulated labour-market report shows persistent competition for skilled staff.", "Учебный обзор рынка труда указывает на сохраняющуюся конкуренцию за специалистов.",
         "Teacher compensation affects delivery economics." if edu else "Skilled labour is needed to maintain manufacturing output.",
         "Оплата преподавателей влияет на экономику услуги." if edu else "Квалифицированный труд необходим для сохранения производственного выпуска.",
         "If wage costs remain firm as demand slows, margin pressure could increase. Compare staffing plans with actual utilisation and retention, rather than applying a uniform hiring freeze.",
         "Если зарплаты останутся высокими при замедлении спроса, давление на маржу усилится. Сверьте кадровые планы с загрузкой и удержанием вместо общей заморозки найма.",
         "Operations · This week: review capacity utilisation and retention in critical teams.", "Операционный отдел · На этой неделе: проверить загрузку и удержание в ключевых командах."),
        (11, "opportunity", "competition", 76, "Partnership demand is worth validating", "Спрос на партнёрства стоит проверить",
         "A simulated industry survey reports interest in longer-term supplier partnerships.", "Учебный отраслевой опрос сообщает об интересе к долгосрочным партнёрствам с поставщиками.",
         "School partnerships are a stated strategic priority." if edu else "Long-term industrial buyers are central to your sales model.",
         "Партнёрства со школами указаны среди приоритетов." if edu else "Долгосрочные промышленные клиенты важны для вашей модели продаж.",
         "The survey suggests a potential route to more predictable revenue, but stated interest is not signed demand. Validate willingness to commit and contract-level margins before scaling outreach.",
         "Опрос указывает на возможность более предсказуемой выручки, но интерес не равен контракту. Проверьте готовность к обязательствам и маржу до расширения продаж.",
         "Sales · Within two weeks: interview three existing clients about annual commitments.", "Продажи · За две недели: обсудить годовые обязательства с тремя действующими клиентами."),
        (19, "mixed", "macro", 74, "Slower demand calls for selective investment", "Замедление спроса требует избирательных инвестиций",
         "A simulated macroeconomic release points to uneven business activity across sectors.", "Учебная макростатистика указывает на неравномерную деловую активность по отраслям.",
         "Your growth plans depend on customer spending and predictable cash generation.", "Планы роста зависят от расходов клиентов и предсказуемого денежного потока.",
         "An uneven slowdown may affect customer segments differently. Prioritise projects with measurable near-term cash benefits while preserving options in segments where demand is holding up.",
         "Неравномерное замедление по-разному затронет клиентские сегменты. Выделите проекты с измеримым денежным эффектом и сохраните возможности в устойчивых сегментах.",
         "Strategy · This month: update the investment shortlist using segment-level demand and cash-flow evidence.", "Стратегия · В этом месяце: обновить список инвестпроектов по спросу и денежному потоку каждого сегмента."),
        (25, "opportunity", "technology", 71, "A small automation pilot can de-risk expansion", "Небольшой пилот автоматизации снижает риск расширения",
         "A simulated operational study documents reduced manual handling after process automation.", "Учебное операционное исследование описывает сокращение ручных операций после автоматизации.",
         "Your operating teams face pressure to scale without matching growth in fixed costs.", "Операционные команды должны масштабироваться без сопоставимого роста постоянных расходов.",
         "A focused pilot could reveal whether automation is viable in your process. Benefits depend on integration effort and error rates; findings from another company cannot establish your ROI.",
         "Ограниченный пилот покажет применимость автоматизации к вашему процессу. Эффект зависит от интеграции и ошибок; чужой результат не подтверждает вашу окупаемость.",
         "Operations · Next month: pilot one repetitive workflow and measure baseline time and errors.", "Операционный отдел · В следующем месяце: автоматизировать один повторяемый процесс, измерив время и ошибки до и после."),
    ]
    job = Job(workspace_id=ws.id, user_id=user.id, kind="analyze", status="completed", progress=100, started_at=now(), finished_at=now(), input={"demo": True}, result={"events": len(examples)}, steps=[{"name": n, "at": now(), "status": "demonstration", "tool": t, "message": "Synthetic scenario; this trace illustrates the live pipeline structure."} for n,t in [("plan","company_profile"),("collect_and_deduplicate","scenario_fixtures"),("rank","company_relevance"),("retrieve_bank_research","bm25_bilingual_research"),("interpret","demonstration_analysis"),("verify","fixture_validation")]])
    db.add(job);db.flush()
    for idx, row in enumerate(examples):
        days,sentiment,category,score,title_en,title_ru,fact_en,fact_ru,why_en,why_ru,impact_en,impact_ru,action_en,action_ru=row
        date=(datetime.now(timezone.utc)-timedelta(days=days,hours=idx+1)).isoformat(timespec="seconds").replace("+00:00","Z")
        article=record(db,ws.id,"article",{"title":title_en,"url":"","text":fact_en+"\n"+fact_ru,"published_at":date,"source_name":"Synthetic scenario / Учебный сценарий","evidence_level":"synthetic","is_demo":True},key=f"demo:{idx}")
        bank=retrieve_bank(db, title_en+" "+why_en,limit=1)
        bank_view_en="No verified bank opinion is attached to this synthetic event. Explore dated bank research in the evidence library."
        bank_view_ru="К учебному событию не привязана подтверждённая позиция банка. Датированные обзоры доступны в библиотеке источников."
        verified_bank=[]
        bank_quote=""
        if idx==0:
            original_id='1riR1lhsb6EY1MwGMxdBlS_tI5ed9mIiz' if edu else '1shHG89LtMgHT1_uEebHmQSFZe_zbeq7-'
            original=db.query(Item).filter_by(workspace_id='global',kind='bank',key=original_id).first()
            if original:
                p=original.payload
                fragment=(p.get('pages_content') or [{'text':p['text']}])[0]['text'][:2100]
                candidate_quote='Мы полагаем, что динамика потребления сейчас находится Ha пике' if edu else 'ЦБ РФ принял решение оставить ставку неизменной на уровне 14,0%'
                if candidate_quote in fragment:
                    bank_quote=candidate_quote
                    verified_bank=[{'id':original.id,'page':1,'title':p['title'],'url':p['url'],'published_at':p['published_at'],'date_precision':'day','text':fragment,'ocr':True,'user_attributed':False}]
                    bank_view_en="In its 5 August 2026 case report, Alfa-Bank expected consumer demand growth to cool. This is historical context for consumer-sensitive subscriptions, not a forecast of SubSchool's revenue." if edu else "In its 11 September 2026 case report, Alfa-Bank described a pause in rate cuts and firmer central-bank rhetoric. This is historical context for the financing scenario, not the bank's current view."
                    bank_view_ru="В обзоре от 5 августа 2026 года Альфа-Банк ожидал замедления роста потребления. Это исторический контекст для подписок, зависящих от бюджетов клиентов, а не прогноз выручки SubSchool." if edu else "В обзоре от 11 сентября 2026 года Альфа-Банк описывал паузу в снижении ставки и ужесточение риторики ЦБ. Это исторический контекст сценария финансирования, а не текущая позиция банка."
        content={"article_id":article.id,"article":pack(article),"relevance":score,"confidence":72,"sentiment":sentiment,"category":category,"time_horizon":"weeks","profile_features":["exposures","priorities"],"evidence_ids":[article.id],"bank_ids":[],"bank_evidence":[],"related_research":bank,"en":{"title":title_en,"fact":fact_en,"why":why_en,"impact":impact_en,"bank_view":bank_view_en,"actions":[action_en],"uncertainties":["Synthetic scenario. Validate company contract terms and financial exposures before acting."]},"ru":{"title":title_ru,"fact":fact_ru,"why":why_ru,"impact":impact_ru,"bank_view":bank_view_ru,"actions":[action_ru],"uncertainties":["Учебный сценарий. До действий уточните условия договоров и финансовые риски компании."]},"published_at":date,"generated_at":now(),"decision_role":"ceo","profile_version":1,"job_id":job.id,"is_demo":True,"status":"demonstration","verification":{"supported":True,"issues":[],"method":"synthetic fixture"}}
        content.update(bank_ids=[b['id'] for b in verified_bank],bank_evidence=verified_bank,bank_quote=bank_quote)
        saved=record(db,ws.id,"event",content,key=f"demo:{idx}")
        if score>=80:
            record(db,ws.id,"alert",{"event_id":saved.id,"en":title_en,"ru":title_ru,"sentiment":sentiment,"relevance":score,"read_by":[]},key=saved.id)
    for source in [{"name":"Bank of Russia · Press releases","url":"https://www.cbr.ru/rss/RssPress","type":"rss","kind":"news"},{"name":"EdSurge · Education & technology" if edu else "BBC · Business","url":"https://www.edsurge.com/articles_rss" if edu else "https://feeds.bbci.co.uk/news/business/rss.xml","type":"rss","kind":"news"}]:
        record(db,ws.id,"source",{**source,"enabled":True,"health":"not_checked","respect_robots":True,"limit":12,"note":"Live collection is available on demand. Automatic runs are disabled for demo workspaces."})
    db.commit()
    return ws
