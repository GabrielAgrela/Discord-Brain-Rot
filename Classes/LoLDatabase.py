import sqlite3
from datetime import datetime
import os

import aiohttp

class LoLDatabase:
    def __init__(self):
        self.db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../lol_database.db'))
        #self.create_database()

    def create_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create matches table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT PRIMARY KEY,
            game_duration INTEGER,
            game_version TEXT,
            game_mode TEXT,
            game_type TEXT,
            game_creation TIMESTAMP,
            game_end TIMESTAMP
        )
        ''')

        # Create users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            puuid TEXT,
            riot_id_game_name TEXT,
            riot_id_tagline TEXT
        )
        ''')

        # Create participants table with all the relevant fields
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            puuid TEXT,
            summoner_name TEXT,
            champion_name TEXT,
            champion_id INTEGER,
            team_id INTEGER,
            team_position TEXT,
            individual_position TEXT,
            lane TEXT,
            role TEXT,
            wins BOOLEAN,
            
            -- Combat stats
            kills INTEGER,
            deaths INTEGER,
            assists INTEGER,
            kda REAL,
            kill_participation REAL,
            champion_level INTEGER,
            vision_score INTEGER,
            
            -- Damage stats
            total_damage_dealt INTEGER,
            total_damage_to_champions INTEGER,
            physical_damage_to_champions INTEGER,
            magic_damage_to_champions INTEGER,
            true_damage_to_champions INTEGER,
            total_damage_taken INTEGER,
            
            -- Economy stats
            gold_earned INTEGER,
            gold_spent INTEGER,
            total_minions_killed INTEGER,
            
            -- Vision stats
            vision_wards_bought INTEGER,
            sight_wards_bought INTEGER,
            wards_placed INTEGER,
            wards_killed INTEGER,
            
            -- Game progression
            champion_experience INTEGER,
            time_played INTEGER,
            total_time_spent_dead INTEGER,
            
            -- Items
            item0 INTEGER,
            item1 INTEGER,
            item2 INTEGER,
            item3 INTEGER,
            item4 INTEGER,
            item5 INTEGER,
            item6 INTEGER,
            
            -- Additional Combat Stats
            bounty_level INTEGER,
            killing_sprees INTEGER,
            largest_killing_spree INTEGER,
            largest_multi_kill INTEGER,
            longest_time_spent_living INTEGER,
            double_kills INTEGER,
            triple_kills INTEGER,
            quadra_kills INTEGER,
            penta_kills INTEGER,
            unreal_kills INTEGER,
            
            -- Damage Breakdown
            damage_dealt_to_buildings INTEGER,
            damage_dealt_to_objectives INTEGER,
            damage_dealt_to_turrets INTEGER,
            damage_self_mitigated INTEGER,
            largest_critical_strike INTEGER,
            
            -- Objective Stats
            inhibitor_kills INTEGER,
            inhibitor_takedowns INTEGER,
            inhibitors_lost INTEGER,
            nexus_kills INTEGER,
            nexus_lost INTEGER,
            nexus_takedowns INTEGER,
            turret_kills INTEGER,
            turret_takedowns INTEGER,
            turrets_lost INTEGER,
            
            -- Additional Game Stats
            champion_transform INTEGER,
            consumables_purchased INTEGER,
            items_purchased INTEGER,
            neutral_minions_killed INTEGER,
            total_ally_jungle_minions_killed INTEGER,
            total_enemy_jungle_minions_killed INTEGER,
            total_time_cc_dealt INTEGER,
            total_units_healed INTEGER,
            
            -- Team Stats
            first_blood_assist BOOLEAN,
            first_blood_kill BOOLEAN,
            first_tower_assist BOOLEAN,
            first_tower_kill BOOLEAN,
            game_ended_in_surrender BOOLEAN,
            game_ended_in_early_surrender BOOLEAN,
            team_early_surrendered BOOLEAN,
            
            -- Ability Usage
            spell1_casts INTEGER,
            spell2_casts INTEGER,
            spell3_casts INTEGER,
            spell4_casts INTEGER,
            summoner1_casts INTEGER,
            summoner2_casts INTEGER,
            summoner1_id INTEGER,
            summoner2_id INTEGER,
            
            -- Additional Healing/Shielding Stats
            total_heal INTEGER,
            total_heals_on_teammates INTEGER,
            total_damage_shielded_on_teammates INTEGER,
            
            -- Ping Stats
            all_in_pings INTEGER,
            assist_me_pings INTEGER,
            basic_pings INTEGER,
            command_pings INTEGER,
            danger_pings INTEGER,
            enemy_missing_pings INTEGER,
            enemy_vision_pings INTEGER,
            get_back_pings INTEGER,
            hold_pings INTEGER,
            need_vision_pings INTEGER,
            on_my_way_pings INTEGER,
            push_pings INTEGER,
            retreat_pings INTEGER,
            vision_cleared_pings INTEGER,
            
            -- Player Info
            summoner_level INTEGER,
            riot_id_game_name TEXT,
            riot_id_tagline TEXT,
            profile_icon INTEGER,
            last_game_played TEXT,
            
            FOREIGN KEY (match_id) REFERENCES matches (match_id),
            UNIQUE(match_id, puuid)
        )
        ''')

        # Create champions table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS champions (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            title TEXT,
            image_full TEXT,
            image_sprite TEXT,
            image_group TEXT,
            tags TEXT,  -- Stored as comma-separated values
            partype TEXT,  -- Mana, Energy, etc.
            stats_hp REAL,
            stats_hpperlevel REAL,
            stats_mp REAL,
            stats_mpperlevel REAL,
            stats_movespeed REAL,
            stats_armor REAL,
            stats_armorperlevel REAL,
            stats_spellblock REAL,
            stats_spellblockperlevel REAL,
            stats_attackrange REAL,
            stats_hpregen REAL,
            stats_hpregenperlevel REAL,
            stats_mpregen REAL,
            stats_mpregenperlevel REAL,
            stats_crit REAL,
            stats_critperlevel REAL,
            stats_attackdamage REAL,
            stats_attackdamageperlevel REAL,
            stats_attackspeedperlevel REAL,
            stats_attackspeed REAL
        )
        ''')

        conn.commit()
        conn.close()

    async def insert_match(self, match_data):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Insert match data
        match_id = match_data['metadata']['matchId']
        info = match_data['info']
        
        cursor.execute('''
        INSERT OR IGNORE INTO matches (
            match_id, game_duration, game_version, 
            game_mode, game_type, game_creation, game_end
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            match_id,
            info['gameDuration'],
            info['gameVersion'],
            info['gameMode'],
            info['gameType'],
            datetime.fromtimestamp(info['gameCreation']/1000),
            datetime.fromtimestamp(info['gameEndTimestamp']/1000)
        ))

        # Insert participant data
        for participant in info['participants']:
            # Helper function to safely get values with defaults
            def get_safe(key, default=0):
                return participant.get(key, default)
            
            # Helper function to safely get nested challenge values
            def get_challenge(key, default=0):
                return participant.get('challenges', {}).get(key, default)

            cursor.execute('''
            INSERT OR IGNORE INTO participants (
                match_id, puuid, summoner_name, champion_name, champion_id,
                team_id, team_position, individual_position, lane, role,
                wins, kills, deaths, assists, kda, kill_participation,
                champion_level, vision_score, total_damage_dealt,
                total_damage_to_champions, physical_damage_to_champions,
                magic_damage_to_champions, true_damage_to_champions,
                total_damage_taken, gold_earned, gold_spent,
                total_minions_killed, vision_wards_bought,
                sight_wards_bought, wards_placed, wards_killed,
                champion_experience, time_played, total_time_spent_dead,
                item0, item1, item2, item3, item4, item5, item6,
                bounty_level, killing_sprees, largest_killing_spree,
                largest_multi_kill, longest_time_spent_living, double_kills,
                triple_kills, quadra_kills, penta_kills, unreal_kills,
                damage_dealt_to_buildings, damage_dealt_to_objectives,
                damage_dealt_to_turrets, damage_self_mitigated,
                largest_critical_strike, inhibitor_kills, inhibitor_takedowns,
                inhibitors_lost, nexus_kills, nexus_lost, nexus_takedowns,
                turret_kills, turret_takedowns, turrets_lost, champion_transform,
                consumables_purchased, items_purchased, neutral_minions_killed,
                total_ally_jungle_minions_killed, total_enemy_jungle_minions_killed,
                total_time_cc_dealt, total_units_healed, first_blood_assist,
                first_blood_kill, first_tower_assist, first_tower_kill,
                game_ended_in_surrender, game_ended_in_early_surrender,
                team_early_surrendered, spell1_casts, spell2_casts, spell3_casts,
                spell4_casts, summoner1_casts, summoner2_casts, summoner1_id,
                summoner2_id, total_heal, total_heals_on_teammates,
                total_damage_shielded_on_teammates, all_in_pings, assist_me_pings,
                basic_pings, command_pings, danger_pings, enemy_missing_pings,
                enemy_vision_pings, get_back_pings, hold_pings, need_vision_pings,
                on_my_way_pings, push_pings, retreat_pings, vision_cleared_pings,
                summoner_level, riot_id_game_name, riot_id_tagline, profile_icon
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ''', (
                match_id,
                get_safe('puuid'),
                get_safe('summonerName'),
                get_safe('championName'),
                get_safe('championId'),
                get_safe('teamId'),
                get_safe('teamPosition'),
                get_safe('individualPosition'),
                get_safe('lane'),
                get_safe('role'),
                get_safe('win'),
                get_safe('kills'),
                get_safe('deaths'),
                get_safe('assists'),
                get_challenge('kda'),
                get_challenge('killParticipation'),
                get_safe('champLevel'),
                get_safe('visionScore'),
                get_safe('totalDamageDealt'),
                get_safe('totalDamageDealtToChampions'),
                get_safe('physicalDamageDealtToChampions'),
                get_safe('magicDamageDealtToChampions'),
                get_safe('trueDamageDealtToChampions'),
                get_safe('totalDamageTaken'),
                get_safe('goldEarned'),
                get_safe('goldSpent'),
                get_safe('totalMinionsKilled'),
                get_safe('visionWardsBoughtInGame'),
                get_safe('sightWardsBoughtInGame'),
                get_safe('wardsPlaced'),
                get_safe('wardsKilled'),
                get_safe('champExperience'),
                get_safe('timePlayed'),
                get_safe('totalTimeSpentDead'),
                get_safe('item0'),
                get_safe('item1'),
                get_safe('item2'),
                get_safe('item3'),
                get_safe('item4'),
                get_safe('item5'),
                get_safe('item6'),
                get_safe('bountyLevel'),
                get_safe('killingSprees'),
                get_safe('largestKillingSpree'),
                get_safe('largestMultiKill'),
                get_safe('longestTimeSpentLiving'),
                get_safe('doubleKills'),
                get_safe('tripleKills'),
                get_safe('quadraKills'),
                get_safe('pentaKills'),
                get_safe('unrealKills'),
                get_safe('damageDealtToBuildings'),
                get_safe('damageDealtToObjectives'),
                get_safe('damageDealtToTurrets'),
                get_safe('damageSelfMitigated'),
                get_safe('largestCriticalStrike'),
                get_safe('inhibitorKills'),
                get_safe('inhibitorTakedowns'),
                get_safe('inhibitorsLost'),
                get_safe('nexusKills'),
                get_safe('nexusLost'),
                get_safe('nexusTakedowns'),
                get_safe('turretKills'),
                get_safe('turretTakedowns'),
                get_safe('turretsLost'),
                get_safe('championTransform'),
                get_safe('consumablesPurchased'),
                get_safe('itemsPurchased'),
                get_safe('neutralMinionsKilled'),
                get_safe('totalAllyJungleMinionsKilled'),
                get_safe('totalEnemyJungleMinionsKilled'),
                get_safe('totalTimeCCDealt'),
                get_safe('totalUnitsHealed'),
                get_safe('firstBloodAssist'),
                get_safe('firstBloodKill'),
                get_safe('firstTowerAssist'),
                get_safe('firstTowerKill'),
                get_safe('gameEndedInSurrender'),
                get_safe('gameEndedInEarlySurrender'),
                get_safe('teamEarlySurrendered'),
                get_safe('spell1Casts'),
                get_safe('spell2Casts'),
                get_safe('spell3Casts'),
                get_safe('spell4Casts'),
                get_safe('summoner1Casts'),
                get_safe('summoner2Casts'),
                get_safe('summoner1Id'),
                get_safe('summoner2Id'),
                get_safe('totalHeal'),
                get_safe('totalHealsOnTeammates'),
                get_safe('totalDamageShieldedOnTeammates'),
                get_safe('allInPings'),
                get_safe('assistMePings'),
                get_safe('basicPings'),
                get_safe('commandPings'),
                get_safe('dangerPings'),
                get_safe('enemyMissingPings'),
                get_safe('enemyVisionPings'),
                get_safe('getBackPings'),
                get_safe('holdPings'),
                get_safe('needVisionPings'),
                get_safe('onMyWayPings'),
                get_safe('pushPings'),
                get_safe('retreatPings'),
                get_safe('visionClearedPings'),
                get_safe('summonerLevel'),
                get_safe('riotIdGameName'),
                get_safe('riotIdTagline'),
                get_safe('profileIcon')
            ))

        conn.commit()
        conn.close()

    async def get_player_stats(self, username, gamemode, champion=None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        base_query = '''
        WITH base_data AS (
            SELECT p.*, m.game_duration, m.game_creation
            FROM participants p
            JOIN matches m ON p.match_id = m.match_id
            WHERE LOWER(p.riot_id_game_name) = LOWER(?)
            AND LOWER(m.game_mode) = LOWER(?)
            {champion_filter}
        ),
        champion_stats AS (
            SELECT 
                champion_name,
                COUNT(*) as total_games,
                ROUND(AVG(CASE WHEN wins = 1 THEN 100.0 ELSE 0 END), 1) as winrate,
                ROUND(AVG(total_damage_to_champions / (game_duration / 60.0)), 0) as avg_damage_per_minute,
                ROUND(AVG(kda), 2) as average_kda,
                ROUND(AVG(CAST(kills AS FLOAT)), 1) as avg_kills,
                ROUND(AVG(CAST(deaths AS FLOAT)), 1) as avg_deaths,
                ROUND(AVG(CAST(assists AS FLOAT)), 1) as avg_assists,
                SUM(triple_kills) as total_triples,
                SUM(quadra_kills) as total_quadras,
                SUM(penta_kills) as total_pentas
            FROM base_data
            GROUP BY champion_name
            {having_clause}
        )
        SELECT 
            champion_name,
            total_games as champion_games,
            winrate,
            avg_damage_per_minute,
            average_kda,
            (SELECT COUNT(*) FROM base_data) as total_games_overall,
            (SELECT COUNT(DISTINCT champion_name) FROM base_data) as unique_champions_played,
            ROUND(CAST((SELECT COUNT(DISTINCT champion_name) FROM base_data) AS FLOAT) / 
                (SELECT COUNT(*) FROM base_data) * 100, 1) as unique_champ_ratio,
            (SELECT MIN(game_creation) FROM base_data) as oldest_game,
            ROUND(CAST((SELECT SUM(game_duration) FROM base_data) AS FLOAT) / 3600, 1) as total_hours_played,
            total_triples,
            total_quadras,
            total_pentas,
            (SELECT SUM(penta_kills) FROM base_data) as total_pentas_overall
        FROM champion_stats
        ORDER BY champion_games DESC, winrate DESC
        LIMIT 20;
        '''

        if champion:
            # If champion is specified, filter for that champion and remove the HAVING clause
            query = base_query.format(
                champion_filter="AND LOWER(p.champion_name) = LOWER(?)",
                having_clause=""
            )
            cursor.execute(query, (username, gamemode, champion))
        else:
            # Original behavior: show champions with 4 or more games
            query = base_query.format(
                champion_filter="",
                having_clause="HAVING total_games >= 4"
            )
            cursor.execute(query, (username, gamemode))

        results = cursor.fetchall()
        conn.close()
        return results

    async def get_player_time_stats(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = '''
        WITH earliest_match AS (
            SELECT 
                puuid, 
                MIN(m.game_creation) AS first_game_date,
                (SELECT p2.match_id 
                 FROM participants p2 
                 JOIN matches m2 ON p2.match_id = m2.match_id 
                 WHERE p2.puuid = p1.puuid 
                 ORDER BY m2.game_creation ASC LIMIT 1) AS first_match_id
            FROM participants p1
            JOIN matches m ON p1.match_id = m.match_id
            GROUP BY p1.puuid
        )
        SELECT 
            p.riot_id_game_name,
            p.riot_id_tagline,
            ROUND(SUM(p.time_played) / 3600.0, 2) AS total_hours_played,
            ROUND(
                SUM(
                    CASE 
                        WHEN strftime('%Y', m.game_creation) = '2024' 
                        THEN p.time_played 
                        ELSE 0 
                    END
                ) / 3600.0, 2
            ) AS total_hours_2024,
            COUNT(p.match_id) AS games_played,
            ROUND(AVG(p.time_played) / 60.0, 2) AS avg_minutes_per_game,
            e.first_game_date,
            SUM(p.penta_kills) as total_pentas,
            ROUND(100.0 * SUM(CASE WHEN p.wins = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) as winrate
        FROM participants p
        JOIN matches m ON p.match_id = m.match_id
        JOIN earliest_match e ON p.puuid = e.puuid
        JOIN participants ep ON ep.puuid = e.puuid AND ep.match_id = e.first_match_id
        GROUP BY p.puuid
        ORDER BY total_hours_played DESC
        LIMIT 20;
        '''
        
        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()
        return results

    async def get_player_friend_stats(self, username):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = '''
        WITH my_matches AS (
            SELECT 
                p.match_id, 
                p.team_id, 
                CASE WHEN p.wins = 1 THEN 1 ELSE 0 END AS my_win
            FROM participants p
            WHERE LOWER(p.riot_id_game_name) = LOWER(?)
        ),
        teammates AS (
            SELECT
                p2.riot_id_game_name AS teammate_name,
                COUNT(*) AS games_together,
                SUM(CASE WHEN m.my_win = 1 THEN 1 ELSE 0 END) AS wins_together,
                ROUND(
                    100.0 * SUM(CASE WHEN m.my_win = 1 THEN 1 ELSE 0 END) 
                    / COUNT(*), 1
                ) AS win_rate
            FROM my_matches m
            JOIN participants p2 ON p2.match_id = m.match_id
            WHERE p2.team_id = m.team_id
              AND LOWER(p2.riot_id_game_name) <> LOWER(?)
            GROUP BY p2.riot_id_game_name
            HAVING COUNT(*) >= 5
        )
        SELECT *
        FROM teammates
        ORDER BY win_rate DESC, games_together DESC
        LIMIT 15;
        '''
        
        cursor.execute(query, (username, username))
        results = cursor.fetchall()
        conn.close()
        return results

    async def insert_user(self, username, puuid, riot_id_game_name, riot_id_tagline):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT OR REPLACE INTO users (
            username, puuid, riot_id_game_name, riot_id_tagline
        ) VALUES (?, ?, ?, ?)
        ''', (username, puuid, riot_id_game_name, riot_id_tagline))
        
        conn.commit()
        conn.close()

    async def update_user(self, username, puuid = None, riot_id_game_name = None, riot_id_tagline = None, last_game_played = None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Build update query dynamically based on non-None values
        update_fields = []
        params = []
        if puuid is not None:
            update_fields.append("puuid = ?")
            params.append(puuid)
        if riot_id_game_name is not None:
            update_fields.append("riot_id_game_name = ?") 
            params.append(riot_id_game_name)
        if riot_id_tagline is not None:
            update_fields.append("riot_id_tagline = ?")
            params.append(riot_id_tagline)
        if last_game_played is not None:
            update_fields.append("last_game_played = ?")
            params.append(last_game_played)
            
        if update_fields:
            query = f"UPDATE users SET {', '.join(update_fields)} WHERE username = ?"
            params.append(username)
            cursor.execute(query, params)
            
        conn.commit()
        conn.close()

    async def get_stored_match_ids(self, puuid):
        """Get all match IDs stored in the database for a specific puuid and matches with 0 duration"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DISTINCT match_id 
            FROM participants 
            WHERE puuid = ?
            UNION
            SELECT match_id
            FROM matches
            WHERE game_duration = 0
        ''', (puuid,))
        stored_matches = set(row[0] for row in cursor.fetchall())
        conn.close()
        return stored_matches

    async def get_match_count(self):
        """Get the total number of matches stored in the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM matches')
        count = cursor.fetchone()[0]
        conn.close()
        return count

    async def get_users(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users')
        results = cursor.fetchall()
        conn.close()
        return results
    
    async def get_champion(self, id):
        url = "https://ddragon.leagueoflegends.com/cdn/14.24.1/data/en_US/champion.json"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                # Search through champions to find matching ID
                for champ_name, champ_data in data['data'].items():
                    if int(champ_data['key']) == id:
                        return champ_data['name']
        return None
    