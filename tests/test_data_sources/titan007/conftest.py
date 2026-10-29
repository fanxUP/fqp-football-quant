from pathlib import Path

import pytest

from scripts.sources.titan007 import companies, store


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    conn = store.connect(path)
    conn.execute(
        "INSERT INTO matches (match_id, match_date, kickoff, league_id, league_name,"
        " home_id, home_name, away_id, away_name, status_code, status_text,"
        " home_score, away_score, home_half, away_half)"
        " VALUES (1,'2026-10-19','2026-10-19 20:00',25,'英超',100,'主队',200,'客队',"
        "-1,'完',2,1,1,0)"
    )
    conn.execute(
        "INSERT INTO matches (match_id, match_date, kickoff, league_id, league_name,"
        " home_id, home_name, away_id, away_name, status_code, status_text)"
        " VALUES (2,'2026-10-20','2026-10-20 03:00',25,'英超',100,'主队',300,'客队三',"
        "0,'未')"
    )
    conn.execute(
        "INSERT INTO matches (match_id, match_date, kickoff, league_id, league_name,"
        " home_id, home_name, away_id, away_name, status_code, status_text,"
        " home_score, away_score)"
        " VALUES (3,'2026-10-20','2026-10-20 05:00',25,'英超',500,'甲队',600,'乙队',"
        "-1,'完场',0,0)"
    )
    conn.execute(
        "INSERT INTO matches (match_id, match_date, kickoff, league_id, league_name,"
        " home_id, home_name, away_id, away_name, status_code, status_text)"
        " VALUES (4,'2027-01-01','2027-01-01 20:00',25,'英超',500,'甲队',600,'乙队',"
        "0,'未开赛')"
    )
    conn.execute("INSERT INTO match_stats VALUES (1,'射门','10','5')")
    conn.execute(
        "INSERT INTO events (match_id,seq,minute,side,event_type,player_name,assist_name)"
        " VALUES (1,1,'12','home','入球','主队前锋','主队边锋')"
    )
    conn.execute(
        "INSERT INTO lineups (match_id,side,player_name,player_id,number,position,starter)"
        " VALUES (1,'home','主队前锋',1001,'9','前锋',1)"
    )
    conn.execute(
        "INSERT INTO lineups (match_id,side,player_name,player_id,number,position,starter)"
        " VALUES (2,'home','替补甲',3001,'18','中场',0)"
    )
    conn.execute("INSERT INTO leagues (league_id,name_simplified,kind) VALUES (25,'英超',1)")
    conn.execute("INSERT INTO leagues (league_id,name_simplified,kind) VALUES (889,'杯赛',2)")
    conn.execute(
        "INSERT INTO league_categories (league_id,region,country,type,audience,tier,priority)"
        " VALUES (25,'欧洲','英格兰','league','men',1,'S')"
    )
    conn.execute(
        "INSERT INTO league_categories (league_id,region,country,type,audience,tier,priority)"
        " VALUES (889,'欧洲','国际','cup','men',0,'C')"
    )
    conn.execute("INSERT INTO league_info (league_id,season,name) VALUES (889,'2026','杯赛')")
    conn.execute(
        "INSERT INTO league_standings (league_id,season,scope,period,team_id,rank,played,"
        "win,draw,loss,goals_for,goals_against,goal_diff,points)"
        " VALUES (889,'2026','S1A','total',400,1,3,2,1,0,6,2,4,7)"
    )
    conn.execute(
        "INSERT INTO team_profiles (team_id,name,logo,city,stadium)"
        " VALUES (400,'杯赛队','images/400/x.png','杯赛城','杯赛球场')"
    )
    conn.execute(
        "INSERT INTO lottery_matches (lottery_match_id,match_date,match_num,"
        " home_team_id,home_full_name,away_team_id,away_full_name,titan_match_id,"
        " home_score,away_score,half_score,odds_h,odds_d,odds_a,goal_line,win_flag)"
        " VALUES (100,'2026-10-19','周一001',9001,'主队',9002,'客队',1,"
        " 2,1,'1:0',2.1,3.2,3.4,-0.5,'H')"
    )
    conn.execute("INSERT INTO league_teams (league_id,team_id,name) VALUES (25,555,'联赛队')")
    conn.execute(
        "INSERT INTO predicted_lineups (match_id,side,player_name,number,coach_name)"
        " VALUES (1,'home','主队前锋','9','教练甲')"
    )
    conn.execute(
        "INSERT INTO competition_formats (league_id,season,format) VALUES (25,'2026-2027','league')"
    )
    conn.execute(
        "INSERT INTO cup_ties (league_id,season,round,team_a,team_b,legs,score_a,score_b,winner_team_id)"
        " VALUES (25,'2026-2027',1,100,200,2,3,1,100)"
    )
    conn.execute(
        "INSERT INTO league_results (match_id,league_id,season,round,status,match_time,"
        "home_id,away_id,home_score,away_score)"
        " VALUES (1,25,'2026-2027',1,-1,'2026-10-19 20:00',100,200,2,1)"
    )
    conn.execute(
        "INSERT INTO league_results (match_id,league_id,season,round,status,match_time,"
        "home_id,away_id,home_score,away_score)"
        " VALUES (2,25,'2026-2027',2,-1,'2026-10-20 03:00',100,300,0,0)"
    )
    conn.execute(
        "INSERT INTO league_standings (league_id,season,scope,period,team_id,rank,played,"
        "win,draw,loss,goals_for,goals_against,goal_diff,points)"
        " VALUES (25,'2026-2027','total','total',100,1,10,7,2,1,20,8,12,23)"
    )
    conn.execute(
        "INSERT INTO scorers (league_id,season,scope,player_id,rank,name,team_id,goals)"
        " VALUES (25,'2026-2027','total',1001,1,'主队前锋',100,9)"
    )
    conn.execute(
        "INSERT INTO team_profiles (team_id,name,logo,city,stadium)"
        " VALUES (100,'主队','images/100/x.png','主队城','主队球场')"
    )
    conn.execute(
        "INSERT INTO team_profiles (team_id,name,logo,city,stadium)"
        " VALUES (700,'=1+1队','images/700/x.png','公式城','公式球场')"
    )
    conn.execute(
        "INSERT INTO team_squad (team_id,player_id,number,name,position,nationality)"
        " VALUES (100,1001,'9','主队前锋','前锋','中国')"
    )
    conn.execute(
        "INSERT INTO team_squad (team_id,player_id,number,name,position,nationality)"
        " VALUES (100,2001,'9','主队前锋','前锋','中国')"
    )
    conn.execute(
        "INSERT INTO assets (asset_type,entity_id,name,url,path,bytes,status,fetched_at)"
        " VALUES ('team_logo',100,'主队','http://x/teams/100.png',"
        "'data/images/teams/100.png',100,'ok','2026-10-20T00:00:00')"
    )
    conn.execute(
        "INSERT INTO odds (match_id,company_id,company_name,odds_type,source,"
        " initial_home,initial_line,initial_away,live_home,live_line,live_away)"
        " VALUES (1,3,'Crown','europe','feed',2.1,3.2,3.4,2.0,3.3,3.6)"
    )
    conn.execute(
        "INSERT INTO odds (match_id,company_id,company_name,odds_type,source,"
        " initial_home,initial_line,initial_away,live_home,live_line,live_away)"
        " VALUES (1,4,'NullBook','asian','feed',NULL,NULL,NULL,NULL,NULL,NULL)"
    )
    conn.execute(
        "INSERT INTO odds_history (match_id,company_id,odds_type,source,seq,"
        " home,line,away,change_time,status)"
        " VALUES (1,3,'europe','vip',1,2.1,'3.2',3.4,'2026-10-19 18:00','初')"
    )
    conn.execute(
        "INSERT INTO analysis_sections (match_id,section,payload)"
        " VALUES (1,'briefing','{\"text\":\"简报内容\"}')"
    )
    conn.execute(
        "INSERT INTO analysis_sections (match_id,section,payload)"
        ' VALUES (1,\'injuries\',\'[{"team_name":"主队","number":"9","position":"前锋","player_name":"主队前锋","reason":"测试伤病"}]\')'
    )
    conn.execute(
        "INSERT INTO player_stats (match_id,side,seq,number,player,player_id,position,rating,data_json)"
        " VALUES (1,'home',1,'9','主队前锋',1001,'前锋',7.5,'{\"射门\":\"3\"}')"
    )
    conn.execute(
        "INSERT INTO jc_odds (match_id,market,phase,home,draw,away,line,payload_json)"
        " VALUES (1,'sf','first',2.1,3.2,3.4,-1,'{\"win\":2.1}')"
    )
    conn.execute(
        "INSERT INTO odds_alerts (match_id,company_id,company_name,odds_type,source,"
        " field,old_value,new_value,change_time,detected_at)"
        " VALUES (1,3,'Crown','europe','vip','home','2.2','2.0',"
        "'2026-10-19 18:30','2026-10-19T18:31:00')"
    )
    conn.execute(
        "INSERT INTO text_live (match_id,title,content,fetched_at)"
        " VALUES (1,'文字直播','12分钟 主队进球','2026-10-19T20:10:00')"
    )
    companies.sync_companies(conn)
    conn.commit()
    conn.close()
    return path
