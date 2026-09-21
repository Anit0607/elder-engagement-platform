import React, {useEffect, useState} from 'react';
import {
  Alert,
  AppState,
  Pressable,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import {SafeAreaProvider, useSafeAreaInsets} from 'react-native-safe-area-context';
import {copy, type Language} from './src/copy';
import {checkMemberSignIn, getSavedLanguage, openMemberPhoneSignIn, saveLanguage, signOutMember} from './src/memberSession';
import {ProfileEditor} from './src/ProfileEditor';
import {DeviceControls} from './src/DeviceControls';
import {CircleDiscovery} from './src/CircleDiscovery';

type Tab = 'home' | 'circles' | 'profile';
const languages: Language[] = ['en', 'bn', 'hi'];
const tabs: Tab[] = ['home', 'circles', 'profile'];

export default function App() {
  return (
    <SafeAreaProvider>
      <StatusBar backgroundColor="#f6f8f6" barStyle="dark-content" />
      <AppContent />
    </SafeAreaProvider>
  );
}

function AppContent() {
  const insets = useSafeAreaInsets();
  const [language, setLanguage] = useState<Language>('en');
  const [tab, setTab] = useState<Tab>('home');
  const [account, setAccount] = useState<'checking' | 'signedIn' | 'signedOut' | 'error'>('checking');
  const t = copy[language];

  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const signedIn = await checkMemberSignIn();
        if (active) {setAccount(signedIn ? 'signedIn' : 'signedOut');}
      } catch {
        if (active) {setAccount('error');}
      }
    }
    refresh();
    const listener = AppState.addEventListener('change', state => {
      if (state === 'active') {refresh();}
    });
    return () => {active = false; listener.remove();};
  }, []);

  useEffect(() => {
    let active = true;
    getSavedLanguage().then(saved => {if (active) {setLanguage(saved);}}).catch(() => {});
    return () => {active = false;};
  }, []);

  function chooseLanguage(value: Language) {
    setLanguage(value);
    saveLanguage(value).catch(() => {});
  }

  async function openSignIn() {
    try {await openMemberPhoneSignIn(language);}
    catch {setAccount('error');}
  }

  async function retryAccount() {
    setAccount('checking');
    try {setAccount(await checkMemberSignIn() ? 'signedIn' : 'signedOut');}
    catch {setAccount('error');}
  }

  function confirmSignOut() {
    Alert.alert(t.signOut, t.confirmSignOut, [
      {text: t.cancel, style: 'cancel'},
      {text: t.signOut, style: 'destructive', onPress: () => {
        signOutMember().then(() => setAccount('signedOut')).catch(() => setAccount('error'));
      }},
    ]);
  }

  const profileBody = account === 'checking' ? t.checkingAccount :
    account === 'signedIn' ? t.signedIn :
    account === 'error' ? t.accountUnavailable : t.profileCardBody;

  return (
    <View style={[styles.screen, {paddingTop: insets.top}]}>
      <View style={styles.header}>
        <View>
          <Text style={styles.brand}>amiko</Text>
          <Text style={styles.eyebrow}>{t.tagline}</Text>
        </View>
        <View style={styles.languageRow} accessibilityLabel={t.language}>
          {languages.map(option => (
            <Pressable
              key={option}
              accessibilityRole="button"
              accessibilityLabel={`${t.language}: ${copy[option].languageName}`}
              accessibilityState={{selected: language === option}}
              onPress={() => chooseLanguage(option)}
              style={[styles.languageButton, language === option && styles.selectedLanguage]}>
              <Text style={[styles.languageText, language === option && styles.selectedLanguageText]}>
                {option.toUpperCase()}
              </Text>
            </Pressable>
          ))}
        </View>
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.sectionLabel}>{t.sectionLabel}</Text>
        <Text style={styles.title}>{t[`${tab}Title`]}</Text>
        <Text style={styles.intro}>{t[`${tab}Intro`]}</Text>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>{t[`${tab}CardTitle`]}</Text>
          <Text style={styles.cardBody}>{tab === 'profile' ? profileBody :
            tab === 'circles' && account === 'error' ? t.accountUnavailable :
            tab === 'circles' && account === 'checking' ? t.checkingAccount : t[`${tab}CardBody`]}</Text>
          {tab === 'circles' && account === 'signedOut' && <Pressable
            accessibilityRole="button" onPress={openSignIn} style={styles.primaryButton}>
            <Text style={styles.primaryButtonText}>{t.signIn}</Text>
          </Pressable>}
          {tab === 'circles' && account === 'error' && <Pressable
            accessibilityRole="button" onPress={retryAccount} style={styles.primaryButton}>
            <Text style={styles.primaryButtonText}>{t.tryAgain}</Text>
          </Pressable>}
          {tab === 'circles' && account === 'signedIn' && <CircleDiscovery language={language} />}
          {tab === 'profile' && (account === 'signedOut' || account === 'signedIn') && (
            <Pressable
              testID="profile-account-action"
              accessibilityRole="button"
              onPress={account === 'signedIn' ? confirmSignOut : openSignIn}
              style={styles.primaryButton}>
              <Text style={styles.primaryButtonText}>{account === 'signedIn' ? t.signOut : t.signIn}</Text>
            </Pressable>
          )}
          {tab === 'profile' && account === 'error' && (
            <Pressable testID="profile-retry" accessibilityRole="button" onPress={retryAccount}
              style={styles.primaryButton}>
              <Text style={styles.primaryButtonText}>{t.tryAgain}</Text>
            </Pressable>
          )}
          {tab === 'profile' && account === 'signedIn' && <ProfileEditor language={language} />}
          {tab === 'profile' && account === 'signedIn' &&
            <DeviceControls language={language} onSignedOut={() => setAccount('signedOut')} />}
        </View>
        {tab === 'home' && <View style={styles.notice}>
          <Text style={styles.noticeTitle}>{t.previewTitle}</Text>
          <Text style={styles.noticeBody}>{t.previewBody}</Text>
        </View>}
      </ScrollView>

      <View style={[styles.nav, {paddingBottom: Math.max(insets.bottom, 12)}]}>
        {tabs.map(item => (
          <Pressable
            key={item}
            testID={`tab-${item}`}
            accessibilityRole="tab"
            accessibilityState={{selected: tab === item}}
            onPress={() => setTab(item)}
            style={[styles.navItem, tab === item && styles.navItemActive]}>
            <Text style={[styles.navText, tab === item && styles.navTextActive]}>
              {t[item]}
            </Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {flex: 1, backgroundColor: '#f6f8f6'},
  header: {
    paddingHorizontal: 24,
    paddingTop: 18,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#e3e9e3',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  brand: {fontSize: 29, fontWeight: '800', color: '#225940', letterSpacing: -1},
  eyebrow: {fontSize: 12, color: '#496251', marginTop: 2},
  languageRow: {flexDirection: 'row', gap: 4},
  languageButton: {paddingHorizontal: 10, paddingVertical: 8, borderRadius: 10, minHeight: 40},
  selectedLanguage: {backgroundColor: '#225940'},
  languageText: {fontSize: 12, fontWeight: '700', color: '#225940'},
  selectedLanguageText: {color: '#ffffff'},
  content: {padding: 24, paddingBottom: 40},
  sectionLabel: {fontSize: 13, fontWeight: '700', color: '#39745a', textTransform: 'uppercase'},
  title: {fontSize: 31, fontWeight: '800', color: '#1b3325', marginTop: 8, lineHeight: 40},
  intro: {fontSize: 17, lineHeight: 27, color: '#405447', marginTop: 12, marginBottom: 26},
  card: {backgroundColor: '#ffffff', borderRadius: 20, padding: 22, borderWidth: 1, borderColor: '#e0e9e1'},
  cardTitle: {fontSize: 20, fontWeight: '700', color: '#1b3325'},
  cardBody: {fontSize: 16, lineHeight: 25, color: '#4b5b50', marginTop: 10},
  primaryButton: {backgroundColor: '#225940', padding: 16, borderRadius: 12, marginTop: 20, minHeight: 52, alignItems: 'center'},
  primaryButtonText: {fontSize: 17, fontWeight: '700', color: '#ffffff'},
  notice: {marginTop: 16, padding: 18, borderRadius: 16, backgroundColor: '#e9f3ec'},
  noticeTitle: {fontSize: 15, fontWeight: '700', color: '#225940'},
  noticeBody: {fontSize: 14, lineHeight: 22, color: '#405447', marginTop: 6},
  nav: {
    flexDirection: 'row',
    gap: 8,
    paddingHorizontal: 16,
    paddingTop: 10,
    backgroundColor: '#ffffff',
    borderTopWidth: 1,
    borderTopColor: '#e0e9e1',
  },
  navItem: {flex: 1, minHeight: 50, justifyContent: 'center', alignItems: 'center', borderRadius: 12},
  navItemActive: {backgroundColor: '#e9f3ec'},
  navText: {fontSize: 15, fontWeight: '600', color: '#576c5d'},
  navTextActive: {color: '#225940', fontWeight: '800'},
});
