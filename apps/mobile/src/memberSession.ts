import {NativeModules} from 'react-native';
import type {Language} from './copy';

type AccountState = {signedIn: boolean};
type NativeMemberSession = {
  openPhoneSignIn(language: Language): Promise<void>;
  checkSignIn(): Promise<AccountState>;
  signOut(): Promise<void>;
  getProfile(): Promise<string | null>;
  updateProfile(json: string): Promise<string>;
  listDevices(): Promise<MemberDevice[]>;
  removeDevice(id: string): Promise<boolean>;
  getUiLanguage(): Promise<Language>;
  setUiLanguage(language: Language): Promise<void>;
  listCircles(): Promise<string>;
  changeCircleMembership(id: string, join: boolean): Promise<void>;
};

function nativeSession(): NativeMemberSession {
  const module = NativeModules.AmikoSession as NativeMemberSession | undefined;
  if (!module) {
    throw new Error('MEMBER_SESSION_UNAVAILABLE');
  }
  return module;
}

export async function checkMemberSignIn(): Promise<boolean> {
  const result = await nativeSession().checkSignIn();
  if (typeof result?.signedIn !== 'boolean') {
    throw new Error('INVALID_ACCOUNT_STATE');
  }
  return result.signedIn;
}

export async function openMemberPhoneSignIn(language: Language): Promise<void> {
  await nativeSession().openPhoneSignIn(language);
}

export async function signOutMember(): Promise<void> {
  await nativeSession().signOut();
}

export async function getSavedLanguage(): Promise<Language> {
  const language = await nativeSession().getUiLanguage();
  return ['en', 'bn', 'hi'].includes(language) ? language : 'en';
}

export async function saveLanguage(language: Language): Promise<void> {
  await nativeSession().setUiLanguage(language);
}

export type MemberProfile = {
  displayName: string;
  preferredLanguage: Language;
  ageGroup: string | null;
  interests: string[];
  broadLocation: {countryCode?: string; state?: string; city?: string} | null;
  notificationWindow: {enabled: boolean; startLocalTime?: string | null; endLocalTime?: string | null; timeZone: string};
};

export type MemberProfileUpdate = Partial<MemberProfile>;

function parseProfile(json: string): MemberProfile {
  const value: unknown = JSON.parse(json);
  if (!value || typeof value !== 'object') {throw new Error('INVALID_PROFILE_RESPONSE');}
  const profile = value as MemberProfile;
  if (typeof profile.displayName !== 'string' ||
      !['en', 'bn', 'hi'].includes(profile.preferredLanguage) ||
      !Array.isArray(profile.interests) ||
      !profile.interests.every(item => typeof item === 'string') ||
      typeof profile.notificationWindow?.enabled !== 'boolean') {
    throw new Error('INVALID_PROFILE_RESPONSE');
  }
  return profile;
}

export async function getMemberProfile(): Promise<MemberProfile | null> {
  const json = await nativeSession().getProfile();
  return json === null ? null : parseProfile(json);
}

export async function updateMemberProfile(change: MemberProfileUpdate): Promise<MemberProfile> {
  return parseProfile(await nativeSession().updateProfile(JSON.stringify(change)));
}

export type MemberDevice = {
  id: string; platform: 'android' | 'ios' | 'web'; current: boolean;
  deviceName: string | null; lastSeenAt: string | null;
};

export async function listMemberDevices(): Promise<MemberDevice[]> {
  const rows = await nativeSession().listDevices();
  if (!Array.isArray(rows) || rows.some(row => typeof row.id !== 'string' ||
      typeof row.current !== 'boolean')) {
    throw new Error('INVALID_DEVICE_RESPONSE');
  }
  return rows;
}

export async function removeMemberDevice(id: string): Promise<boolean> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) {throw new Error('INVALID_DEVICE_ID');}
  return nativeSession().removeDevice(id);
}

export type MemberCircle = {
  id: string; name: string; description: string | null;
  active: boolean; joined: boolean; suggested: boolean;
};

export async function listMemberCircles(): Promise<MemberCircle[]> {
  const value: unknown = JSON.parse(await nativeSession().listCircles());
  if (!Array.isArray(value) || value.length > 100 || value.some(row =>
    !row || typeof row !== 'object' || typeof row.id !== 'string' ||
    !/^[0-9a-f-]{36}$/i.test(row.id) || typeof row.name !== 'string' ||
    (row.description !== null && typeof row.description !== 'string') ||
    typeof row.active !== 'boolean' || typeof row.joined !== 'boolean' ||
    typeof row.suggested !== 'boolean')) {
    throw new Error('INVALID_CIRCLE_RESPONSE');
  }
  return value as MemberCircle[];
}

export async function changeMemberCircle(id: string, join: boolean): Promise<void> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) {throw new Error('INVALID_CIRCLE_ID');}
  await nativeSession().changeCircleMembership(id, join);
}
