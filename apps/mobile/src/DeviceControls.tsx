import React, {useEffect, useState} from 'react';
import {Alert, Pressable, StyleSheet, Text, View} from 'react-native';
import {copy, type Language} from './copy';
import {listMemberDevices, removeMemberDevice, type MemberDevice} from './memberSession';

export function DeviceControls({language, onSignedOut}: {language: Language; onSignedOut: () => void}) {
  const t = copy[language];
  const [devices, setDevices] = useState<MemberDevice[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [changing, setChanging] = useState(false);

  useEffect(() => {
    let active = true;
    listMemberDevices().then(rows => {
      if (active) {setDevices(rows); setStatus('ready');}
    }).catch(() => {if (active) {setStatus('error');}});
    return () => {active = false;};
  }, []);

  function confirmRemoval(device: MemberDevice) {
    Alert.alert(t.removeDevice, t.removeConfirm, [
      {text: t.cancel, style: 'cancel'},
      {text: t.removeDevice, style: 'destructive', onPress: async () => {
        setChanging(true);
        try {
          const signedIn = await removeMemberDevice(device.id);
          if (!signedIn) {onSignedOut(); return;}
          setDevices(await listMemberDevices());
          setStatus('ready');
        } catch {setStatus('error');}
        finally {setChanging(false);}
      }},
    ]);
  }

  return (
    <View style={styles.section}>
      <Text style={styles.heading}>{t.yourDevices}</Text>
      {status === 'loading' && <Text style={styles.message}>{t.checkingAccount}</Text>}
      {status === 'error' && <Text style={styles.error}>{t.deviceLoadFailed}</Text>}
      {status === 'ready' && devices.length === 0 && <Text style={styles.message}>{t.noDevices}</Text>}
      {status === 'ready' && devices.map(device => (
        <View key={device.id} style={styles.row}>
          <View style={styles.rowText}>
            <Text style={styles.name}>{device.current ? t.thisDevice : t.anotherDevice}</Text>
            <Text style={styles.detail}>{device.deviceName || device.platform}</Text>
          </View>
          <Pressable accessibilityRole="button" disabled={changing}
            accessibilityLabel={`${t.removeDevice}: ${device.current ? t.thisDevice : t.anotherDevice}`}
            onPress={() => confirmRemoval(device)} style={styles.removeButton}>
            <Text style={styles.removeText}>{t.removeDevice}</Text>
          </Pressable>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  section: {marginTop: 24, borderTopWidth: 1, borderTopColor: '#dce8df', paddingTop: 18},
  heading: {fontSize: 20, fontWeight: '700', color: '#1b3325'},
  message: {fontSize: 15, color: '#4b5b50', marginTop: 12},
  error: {fontSize: 15, color: '#a52626', marginTop: 12},
  row: {paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: '#e2e9e3',
    flexDirection: 'row', alignItems: 'center', gap: 10},
  rowText: {flex: 1},
  name: {fontSize: 16, color: '#234331', fontWeight: '600'},
  detail: {fontSize: 14, color: '#5d7061', marginTop: 4},
  removeButton: {minHeight: 46, paddingHorizontal: 12, borderRadius: 10,
    justifyContent: 'center', backgroundColor: '#fff2f1'},
  removeText: {fontSize: 14, fontWeight: '700', color: '#9b2c24'},
});
