import pytest
from app import discovery


def test_current_news_discovery_rejects_working_but_stale_promotional_feed(monkeypatch):
    monkeypatch.setattr(discovery,'safe_url',lambda *a,**k:None)
    monkeypatch.setattr(discovery,'allowed_by_robots',lambda u:True)
    monkeypatch.setattr(discovery,'fetch',lambda u,**k:(b'<html><title>Training</title><link rel="alternate" type="application/rss+xml" href="/feed"></html>','text/html',u))
    monkeypatch.setattr(discovery,'collect_source',lambda s:[{'title':'Testimonial','url':'https://example.com/one','published_at':'2023-05-17T00:00:00Z'}]*2)
    with pytest.raises(ValueError,match='No collectable'):
        discovery.verify_publisher({'url':'https://example.com','provider':'Public publisher website inspection','title':'Lead','query':'education Australia'})


def test_collector_does_not_treat_scheduled_future_webinars_as_published_news(monkeypatch):
    from app import collect
    monkeypatch.setattr(collect,'allowed_by_robots',lambda u:True)
    monkeypatch.setattr(collect,'safe_url',lambda *a,**k:None)
    feed=b'''<?xml version="1.0"?><rss version="2.0"><channel><title>Test</title><item><title>Future webinar</title><link>https://example.com/future</link><pubDate>Mon, 01 Jan 2091 00:00:00 GMT</pubDate></item><item><title>Published reporting</title><link>https://example.com/news</link><pubDate>Thu, 22 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>'''
    monkeypatch.setattr(collect,'fetch',lambda u,**k:(feed,'application/rss+xml',u))
    docs=collect.collect_source({'id':'test','name':'Test','url':'https://example.com/feed','limit':10})
    assert [d['title'] for d in docs]==['Published reporting']
