import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
import numpy as np
from datetime import datetime, timedelta
import json

# Configuration
SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']

class SearchConsoleAnalyzer:
    def __init__(self):
        self.service = None
        self.credentials = None
    
    def authenticate_search_console(self, credentials_json):
        """Authenticate with Google Search Console API"""
        try:
            # Load credentials from uploaded JSON
            creds_data = json.loads(credentials_json)
            
            # Use localhost redirect URI (standard for desktop apps)
            redirect_uri = 'http://localhost:8080/callback'
            
            # Create flow object
            flow = Flow.from_client_config(
                creds_data,
                scopes=SCOPES,
                redirect_uri=redirect_uri
            )
            
            # Get authorization URL
            auth_url, _ = flow.authorization_url(
                prompt='consent',
                access_type='offline',
                include_granted_scopes='true'
            )
            return flow, auth_url
            
        except Exception as e:
            st.error(f"Authentication error: {str(e)}")
            return None, None
    
    def complete_authentication(self, flow, authorization_response_url):
        """Complete the OAuth flow with full redirect URL"""
        try:
            flow.fetch_token(authorization_response=authorization_response_url)
            self.credentials = flow.credentials
            self.service = build('searchconsole', 'v1', credentials=self.credentials)
            return True
        except Exception as e:
            st.error(f"Token exchange error: {str(e)}")
            return False
    
    def get_search_analytics_data(self, site_url, start_date, end_date, dimensions=['query']):
        """Fetch search analytics data from Search Console"""
        if not self.service:
            st.error("Please authenticate first")
            return None
        
        request = {
            'startDate': start_date.strftime('%Y-%m-%d'),
            'endDate': end_date.strftime('%Y-%m-%d'),
            'dimensions': dimensions,
            'rowLimit': 25000,
            'startRow': 0
        }
        
        try:
            response = self.service.searchanalytics().query(
                siteUrl=site_url, body=request
            ).execute()
            
            if 'rows' not in response:
                return pd.DataFrame()
            
            # Convert to DataFrame
            data = []
            for row in response['rows']:
                row_data = {
                    'query': row['keys'][0] if dimensions == ['query'] else row['keys'],
                    'clicks': row['clicks'],
                    'impressions': row['impressions'],
                    'ctr': row['ctr'],
                    'position': row['position']
                }
                data.append(row_data)
            
            return pd.DataFrame(data)
            
        except Exception as e:
            st.error(f"Error fetching data: {str(e)}")
            return None
    
    def analyze_zero_click_potential(self, df, min_impressions=100, max_ctr=0.05):
        """Identify queries with zero-click potential"""
        if df is None or df.empty:
            return pd.DataFrame()
        
        # Filter for potential zero-click queries
        zero_click_candidates = df[
            (df['impressions'] >= min_impressions) &
            (df['ctr'] <= max_ctr) &
            (df['position'] <= 10)  # Top 10 positions
        ].copy()
        
        # Calculate zero-click score (higher = more likely to be zero-click)
        zero_click_candidates['zero_click_score'] = (
            (zero_click_candidates['impressions'] / df['impressions'].max()) * 0.4 +
            ((1 - zero_click_candidates['ctr']) / (1 - df['ctr'].min())) * 0.4 +
            ((11 - zero_click_candidates['position']) / 10) * 0.2
        )
        
        # Categorize query types
        zero_click_candidates['query_type'] = zero_click_candidates['query'].apply(
            self.categorize_query_type
        )
        
        return zero_click_candidates.sort_values('zero_click_score', ascending=False)
    
    def categorize_query_type(self, query):
        """Categorize query types that commonly result in zero clicks"""
        query_lower = query.lower()
        
        # Question words that often get direct answers
        question_words = ['what', 'when', 'where', 'who', 'why', 'how', 'is', 'are', 'can', 'will', 'does']
        
        # Definition/information seeking
        definition_words = ['define', 'definition', 'meaning', 'what is', 'what are']
        
        # Calculation/conversion queries
        calculation_words = ['calculate', 'convert', 'calculator', 'formula', 'equation']
        
        # Weather, time, location queries
        instant_answer_words = ['weather', 'time', 'temperature', 'forecast', 'hours', 'phone number', 'address']
        
        if any(word in query_lower for word in definition_words):
            return 'Definition/Information'
        elif any(word in query_lower for word in calculation_words):
            return 'Calculation/Conversion'
        elif any(word in query_lower for word in instant_answer_words):
            return 'Instant Answer'
        elif any(query_lower.startswith(word) for word in question_words):
            return 'Question'
        elif len(query_lower.split()) <= 2:
            return 'Short Query'
        else:
            return 'Other'

def main():
    st.set_page_config(
        page_title="Zero-Click Search Analyzer",
        page_icon="🔍",
        layout="wide"
    )
    
    st.title("🔍 Zero-Click Search Analysis Tool")
    st.markdown("Analyze Google Search Console data to identify keywords triggering zero-click searches")
    
    # Initialize analyzer
    if 'analyzer' not in st.session_state:
        st.session_state.analyzer = SearchConsoleAnalyzer()
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("Configuration")
        
        # Authentication section
        st.subheader("Authentication")
        
        # File uploader for credentials
        uploaded_file = st.file_uploader(
            "Upload Google OAuth2 Credentials JSON",
            type=['json'],
            help="Download from Google Cloud Console"
        )
        
        if uploaded_file and 'flow' not in st.session_state:
            credentials_json = uploaded_file.read().decode()
            flow, auth_url = st.session_state.analyzer.authenticate_search_console(credentials_json)
            
            if flow and auth_url:
                st.session_state.flow = flow
                st.markdown(f"[🔗 Click here to authorize]({auth_url})")
                
                st.markdown("""
                **Instructions:**
                1. Click the authorization link above
                2. Sign in to your Google account
                3. Grant permissions to your app
                4. You'll be redirected to a localhost page that may show "This site can't be reached"
                5. **Copy the entire URL** from your browser address bar
                6. Paste it in the field below
                """)
                
                redirect_url = st.text_input(
                    "Paste the full redirect URL here:",
                    placeholder="http://localhost:8080/callback?code=...",
                    help="Copy the complete URL from your browser after authorization"
                )
                
                if redirect_url and st.button("Complete Authentication"):
                    if st.session_state.analyzer.complete_authentication(st.session_state.flow, redirect_url):
                        st.success("✅ Authentication successful!")
                        st.session_state.authenticated = True
                        st.rerun()
                    else:
                        st.error("❌ Authentication failed")
        
        # Analysis parameters
        st.subheader("Analysis Parameters")
        
        min_impressions = st.slider(
            "Minimum Impressions",
            min_value=50,
            max_value=1000,
            value=100,
            step=50,
            help="Minimum number of impressions to consider"
        )
        
        max_ctr = st.slider(
            "Maximum CTR (%)",
            min_value=1.0,
            max_value=10.0,
            value=5.0,
            step=0.5,
            help="Maximum click-through rate for zero-click candidates"
        ) / 100
        
        # Date range
        st.subheader("Date Range")
        
        end_date = st.date_input(
            "End Date",
            value=datetime.now() - timedelta(days=3)
        )
        
        start_date = st.date_input(
            "Start Date",
            value=end_date - timedelta(days=28)
        )
    
    # Main content
    if st.session_state.get('authenticated', False):
        
        # Site URL input
        site_url = st.text_input(
            "Enter your website URL:",
            placeholder="https://example.com/",
            help="Must be verified in Google Search Console"
        )
        
        if site_url and st.button("🔍 Analyze Zero-Click Potential", type="primary"):
            
            with st.spinner("Fetching Search Console data..."):
                # Fetch data
                df = st.session_state.analyzer.get_search_analytics_data(
                    site_url, start_date, end_date
                )
                
                if df is not None and not df.empty:
                    st.success(f"✅ Fetched {len(df)} queries")
                    
                    # Analyze zero-click potential
                    zero_click_df = st.session_state.analyzer.analyze_zero_click_potential(
                        df, min_impressions, max_ctr
                    )
                    
                    if not zero_click_df.empty:
                        # Display metrics
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            st.metric(
                                "Total Queries Analyzed",
                                f"{len(df):,}"
                            )
                        
                        with col2:
                            st.metric(
                                "Zero-Click Candidates",
                                f"{len(zero_click_df):,}"
                            )
                        
                        with col3:
                            total_impressions = zero_click_df['impressions'].sum()
                            st.metric(
                                "Lost Impressions",
                                f"{total_impressions:,}"
                            )
                        
                        with col4:
                            avg_position = zero_click_df['position'].mean()
                            st.metric(
                                "Avg Position",
                                f"{avg_position:.1f}"
                            )
                        
                        # Visualizations
                        st.subheader("📊 Analysis Results")
                        
                        # Query type distribution
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            query_type_counts = zero_click_df['query_type'].value_counts()
                            fig_pie = px.pie(
                                values=query_type_counts.values,
                                names=query_type_counts.index,
                                title="Zero-Click Candidates by Query Type"
                            )
                            st.plotly_chart(fig_pie, use_container_width=True)
                        
                        with col2:
                            # Scatter plot: Impressions vs CTR
                            fig_scatter = px.scatter(
                                zero_click_df.head(50),
                                x='impressions',
                                y='ctr',
                                color='query_type',
                                size='zero_click_score',
                                hover_data=['query', 'position'],
                                title="Impressions vs CTR (Top 50 Candidates)"
                            )
                            st.plotly_chart(fig_scatter, use_container_width=True)
                        
                        # Top zero-click candidates table
                        st.subheader("🎯 Top Zero-Click Candidates")
                        
                        display_df = zero_click_df.head(20)[
                            ['query', 'impressions', 'clicks', 'ctr', 'position', 'query_type', 'zero_click_score']
                        ].copy()
                        
                        display_df['ctr'] = (display_df['ctr'] * 100).round(2)
                        display_df['position'] = display_df['position'].round(1)
                        display_df['zero_click_score'] = display_df['zero_click_score'].round(3)
                        
                        st.dataframe(
                            display_df,
                            column_config={
                                "query": st.column_config.TextColumn("Query", width="medium"),
                                "impressions": st.column_config.NumberColumn("Impressions", format="%d"),
                                "clicks": st.column_config.NumberColumn("Clicks", format="%d"),
                                "ctr": st.column_config.NumberColumn("CTR (%)", format="%.2f"),
                                "position": st.column_config.NumberColumn("Avg Position", format="%.1f"),
                                "query_type": st.column_config.TextColumn("Query Type", width="small"),
                                "zero_click_score": st.column_config.NumberColumn("Zero-Click Score", format="%.3f")
                            },
                            use_container_width=True
                        )
                        
                        # Download button
                        csv = zero_click_df.to_csv(index=False)
                        st.download_button(
                            label="📥 Download Full Results (CSV)",
                            data=csv,
                            file_name=f"zero_click_analysis_{datetime.now().strftime('%Y%m%d')}.csv",
                            mime="text/csv"
                        )
                        
                        # Recommendations
                        st.subheader("💡 Recommendations")
                        st.markdown("""
                        **For high zero-click potential queries:**
                        
                        1. **Featured Snippets**: Optimize content to win featured snippets for definition and question queries
                        2. **Content Expansion**: Create comprehensive content that encourages clicks beyond the snippet
                        3. **Schema Markup**: Implement relevant schema to enhance SERP features
                        4. **Call-to-Actions**: Add compelling CTAs in meta descriptions and content
                        5. **Long-tail Optimization**: Target related long-tail keywords that require more detailed answers
                        """)
                        
                    else:
                        st.warning("No zero-click candidates found with current parameters. Try adjusting the filters.")
                        
                else:
                    st.error("Failed to fetch data. Please check your site URL and authentication.")
    
    else:
        st.info("👆 Please upload your Google OAuth2 credentials and authenticate to begin analysis.")
        
        st.markdown("""
        ### How to get started:
        
        1. **Set up Google Search Console API:**
           - Go to [Google Cloud Console](https://console.cloud.google.com/)
           - Create a new project or select existing one
           - Enable the Search Console API
           - Create OAuth2 credentials (Desktop application)
           - **Important**: Add `http://localhost:8080/callback` to authorized redirect URIs
           - Download the JSON file
        
        2. **Upload credentials and authenticate**
        
        3. **Enter your verified website URL**
        
        4. **Configure analysis parameters and run analysis**
        
        ### What this tool identifies:
        - Queries with high impressions but low CTR
        - Keywords that might be answered directly in SERPs
        - Potential featured snippet opportunities
        - Query types prone to zero-click searches
        """)

if __name__ == "__main__":
    main()
