import React, {useEffect, useState} from 'react';
import {Image, Pressable, StyleSheet, Switch, Text, TextInput, View} from 'react-native';
import {copy, type Language} from './copy';
import {getMemberProfile, updateMemberProfile, uploadMemberPhoto, type MemberProfileUpdate} from './memberSession';

type Form = {
  name: string; age55: boolean; interests: string; state: string; city: string;
  notify: boolean; start: string; end: string;
};
const emptyForm: Form = {
  name: '', age55: false, interests: '', state: '', city: '',
  notify: false, start: '', end: '',
};

export function makeProfileUpdate(form: Form, language: Language): MemberProfileUpdate {
  const name = form.name.trim();
  if (name.length < 1 || name.length > 120) {throw new Error('INVALID_NAME');}
  const interests = [...new Set(form.interests.split(',').map(item => item.trim()).filter(Boolean))];
  if (interests.length > 30 || interests.some(item => item.length > 80)) {throw new Error('INVALID_INTERESTS');}
  const state = form.state.trim();
  const city = form.city.trim();
  if (state.length > 120 || city.length > 120) {throw new Error('INVALID_LOCATION');}
  const time = /^([01]\d|2[0-3]):[0-5]\d$/;
  if (form.notify && (!time.test(form.start) || !time.test(form.end))) {
    throw new Error('INVALID_TIME');
  }
  return {
    displayName: name,
    preferredLanguage: language,
    ageGroup: form.age55 ? '55+' : null,
    interests,
    broadLocation: state || city ? {countryCode: 'IN', state, city} : null,
    notificationWindow: {
      enabled: form.notify,
      timeZone: 'Asia/Kolkata',
      startLocalTime: form.notify ? form.start : null,
      endLocalTime: form.notify ? form.end : null,
    },
  };
}

export function ProfileEditor({language}: {language: Language}) {
  const t = copy[language];
  const [form, setForm] = useState<Form>(emptyForm);
  const [status, setStatus] = useState<'loading' | 'ready' | 'saving' | 'saved' | 'error'>('loading');
  const [error, setError] = useState<'load' | 'save' | 'name' | 'invalid' | ''>('');
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [photoState, setPhotoState] = useState<'ready' | 'uploading' | 'saved' | 'error'>('ready');
  const [hasProfile, setHasProfile] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setStatus('loading');
    getMemberProfile().then(profile => {
      if (!active) {return;}
      if (profile) {
        setHasProfile(true);
        setPhotoUrl(profile.photoUrl ?? null);
        setForm({
          name: profile.displayName,
          age55: profile.ageGroup === '55+',
          interests: profile.interests.join(', '),
          state: profile.broadLocation?.state ?? '',
          city: profile.broadLocation?.city ?? '',
          notify: profile.notificationWindow.enabled,
          start: profile.notificationWindow.startLocalTime ?? '',
          end: profile.notificationWindow.endLocalTime ?? '',
        });
      }
      setStatus('ready');
    }).catch(() => {if (active) {setStatus('error'); setError('load');}});
    return () => {active = false;};
  }, [loadAttempt]);

  const change = (field: keyof Form, value: string | boolean) => {
    setForm(current => ({...current, [field]: value}));
    if (status === 'saved' || status === 'error') {setStatus('ready'); setError('');}
  };

  async function save() {
    let update: MemberProfileUpdate;
    try {update = makeProfileUpdate(form, language);}
    catch (cause) {
      setStatus('error');
      setError(cause instanceof Error && cause.message === 'INVALID_NAME' ? 'name' : 'invalid');
      return;
    }
    setStatus('saving'); setError('');
    try {
      await updateMemberProfile(update);
      setHasProfile(true);
      setStatus('saved');
    }
    catch {setStatus('error'); setError('save');}
  }

  async function choosePhoto() {
    setPhotoState('uploading');
    try {
      const profile = await uploadMemberPhoto();
      if (profile) {setPhotoUrl(profile.photoUrl ?? null); setPhotoState('saved');}
      else {setPhotoState('ready');}
    } catch {setPhotoState('error');}
  }

  if (status === 'loading') {return <Text style={styles.message}>{t.loadingProfile}</Text>;}
  if (status === 'error' && error === 'load') {
    return <View>
      <Text style={styles.error}>{t.profileLoadFailed}</Text>
      <Pressable accessibilityRole="button" onPress={() => setLoadAttempt(value => value + 1)}
        style={styles.saveButton}>
        <Text style={styles.saveText}>{t.tryAgain}</Text>
      </Pressable>
    </View>;
  }
  return (
    <View style={styles.form}>
      <Text style={styles.label}>{t.yourName}</Text>
      <TextInput testID="profile-name" style={styles.input} value={form.name}
        onChangeText={value => change('name', value)} maxLength={120}
        accessibilityLabel={t.yourName} autoCapitalize="words" />

      <Pressable accessibilityRole="checkbox" accessibilityState={{checked: form.age55}}
        onPress={() => change('age55', !form.age55)} style={styles.choice}>
        <Text style={styles.choiceText}>{form.age55 ? '☑' : '☐'} {t.age55}</Text>
      </Pressable>

      <Text style={styles.label}>{t.interests}</Text>
      <TextInput style={styles.input} value={form.interests}
        onChangeText={value => change('interests', value)} accessibilityLabel={t.interests}
        placeholder={t.interestsHint} maxLength={2500} />

      <Text style={styles.label}>{t.state}</Text>
      <TextInput style={styles.input} value={form.state}
        onChangeText={value => change('state', value)} accessibilityLabel={t.state} maxLength={120} />
      <Text style={styles.label}>{t.city}</Text>
      <TextInput style={styles.input} value={form.city}
        onChangeText={value => change('city', value)} accessibilityLabel={t.city} maxLength={120} />

      <View style={styles.choice}>
        <Text style={styles.choiceText}>{t.notificationTimes}</Text>
        <Switch value={form.notify} onValueChange={value => change('notify', value)}
          accessibilityLabel={t.notificationTimes} />
      </View>
      {form.notify && <>
        <Text style={styles.label}>{t.startTime}</Text>
        <TextInput style={styles.input} value={form.start} onChangeText={value => change('start', value)}
          accessibilityLabel={t.startTime} placeholder="09:00" keyboardType="numbers-and-punctuation" maxLength={5} />
        <Text style={styles.label}>{t.endTime}</Text>
        <TextInput style={styles.input} value={form.end} onChangeText={value => change('end', value)}
          accessibilityLabel={t.endTime} placeholder="20:00" keyboardType="numbers-and-punctuation" maxLength={5} />
      </>}

      {photoUrl?.startsWith('https://storage.googleapis.com/') &&
        <Image source={{uri: photoUrl}} accessibilityLabel={t.profilePhoto} style={styles.photo} />}
      <Pressable accessibilityRole="button" accessibilityState={{disabled: !hasProfile || photoState === 'uploading'}}
        disabled={!hasProfile || photoState === 'uploading'} onPress={choosePhoto}
        style={[styles.photoButton, !hasProfile && styles.photoButtonDisabled]}>
        <Text style={styles.photoButtonText}>{photoState === 'uploading' ? t.uploadingPhoto : t.choosePhoto}</Text>
      </Pressable>
      <Text style={styles.hint}>{hasProfile ? t.photoHelp : t.saveBeforePhoto}</Text>
      {photoState === 'saved' && <Text style={styles.success}>{t.photoSaved}</Text>}
      {photoState === 'error' && <Text style={styles.error}>{t.photoFailed}</Text>}
      <Pressable accessibilityRole="button" accessibilityState={{disabled: status === 'saving'}}
        disabled={status === 'saving'} onPress={save} style={styles.saveButton}>
        <Text style={styles.saveText}>{status === 'saving' ? t.savingProfile : t.saveProfile}</Text>
      </Pressable>
      {status === 'saved' && <Text style={styles.success}>{t.profileSaved}</Text>}
      {status === 'error' && <Text style={styles.error}>{error === 'name' ? t.nameRequired :
        error === 'invalid' ? t.profileInvalid : t.profileSaveFailed}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  form: {marginTop: 20},
  label: {fontSize: 16, fontWeight: '700', color: '#234331', marginTop: 16, marginBottom: 7},
  input: {borderWidth: 1, borderColor: '#b8cdbd', borderRadius: 10, minHeight: 52, paddingHorizontal: 14,
    fontSize: 18, color: '#1b3325', backgroundColor: '#fff'},
  choice: {flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', minHeight: 52, marginTop: 14},
  choiceText: {fontSize: 17, color: '#234331'},
  hint: {fontSize: 14, lineHeight: 22, color: '#5d7061', marginTop: 20},
  photo: {width: 108, height: 108, borderRadius: 54, marginTop: 20},
  photoButton: {minHeight: 52, borderRadius: 10, borderWidth: 1, borderColor: '#225940',
    marginTop: 18, alignItems: 'center', justifyContent: 'center'},
  photoButtonText: {fontSize: 16, fontWeight: '700', color: '#225940'},
  photoButtonDisabled: {opacity: 0.5},
  saveButton: {minHeight: 54, backgroundColor: '#225940', borderRadius: 12, marginTop: 18,
    alignItems: 'center', justifyContent: 'center'},
  saveText: {fontSize: 17, fontWeight: '700', color: '#fff'},
  message: {fontSize: 16, color: '#405447', marginTop: 18},
  success: {fontSize: 16, color: '#225940', marginTop: 12},
  error: {fontSize: 16, color: '#a52626', marginTop: 12},
});
