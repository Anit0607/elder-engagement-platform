import React, {useEffect, useState} from 'react';
import {Alert, Pressable, StyleSheet, Text, View} from 'react-native';
import {copy, type Language} from './copy';
import {changeMemberCircle, listMemberCircles, type MemberCircle} from './memberSession';

export function CircleDiscovery({language}: {language: Language}) {
  const t = copy[language];
  const [circles, setCircles] = useState<MemberCircle[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<'limit' | 'change' | null>(null);

  async function refresh() {
    setStatus('loading');
    try {setCircles(await listMemberCircles()); setStatus('ready');}
    catch {setStatus('error');}
  }

  useEffect(() => {
    let active = true;
    listMemberCircles().then(rows => {
      if (active) {setCircles(rows); setStatus('ready');}
    }).catch(() => {if (active) {setStatus('error');}});
    return () => {active = false;};
  }, []);

  async function change(circle: MemberCircle) {
    setBusyId(circle.id); setMessage(null);
    try {
      await changeMemberCircle(circle.id, !circle.joined);
      setCircles(await listMemberCircles());
    } catch (error) {
      setMessage(error && typeof error === 'object' && 'code' in error &&
        error.code === 'CIRCLE_LIMIT' ? 'limit' : 'change');
    } finally {setBusyId(null);}
  }

  function askChange(circle: MemberCircle) {
    if (!circle.joined) {change(circle); return;}
    Alert.alert(t.leaveCircle, t.leaveCircleConfirm, [
      {text: t.cancel, style: 'cancel'},
      {text: t.leaveCircle, style: 'destructive', onPress: () => change(circle)},
    ]);
  }

  if (status === 'loading') {return <Text style={styles.message}>{t.loadingCircles}</Text>;}
  if (status === 'error') {return <View>
    <Text style={styles.error}>{t.circleLoadFailed}</Text>
    <Pressable accessibilityRole="button" onPress={refresh} style={styles.retry}>
      <Text style={styles.retryText}>{t.tryAgain}</Text>
    </Pressable>
  </View>;}
  if (!circles.length) {return <Text style={styles.message}>{t.noCircles}</Text>;}

  return <View style={styles.list}>
    {message && <Text style={styles.error}>{message === 'limit' ? t.circleLimit : t.circleChangeFailed}</Text>}
    {[...circles].sort((a, b) => Number(b.joined) - Number(a.joined) ||
      Number(b.suggested) - Number(a.suggested) || a.name.localeCompare(b.name)).map(circle => (
        <View key={circle.id} style={styles.row}>
          <View style={styles.titleRow}>
            <Text style={styles.title}>{circle.name}</Text>
            {circle.suggested && !circle.joined && <Text style={styles.badge}>{t.suggested}</Text>}
          </View>
          {circle.description && <Text style={styles.description}>{circle.description}</Text>}
          <Text style={styles.state}>{circle.joined ? t.joinedCircle :
            circle.active ? t.availableCircle : t.inactiveCircle}</Text>
          {(circle.active || circle.joined) && <Pressable
            accessibilityRole="button"
            accessibilityState={{disabled: busyId !== null}}
            disabled={busyId !== null}
            onPress={() => askChange(circle)}
            style={[styles.action, circle.joined && styles.leaveAction]}>
            <Text style={[styles.actionText, circle.joined && styles.leaveText]}>
              {busyId === circle.id ? t.updatingCircle : circle.joined ? t.leaveCircle : t.joinCircle}
            </Text>
          </Pressable>}
        </View>
      ))}
  </View>;
}

const styles = StyleSheet.create({
  list: {marginTop: 12, gap: 12},
  row: {borderWidth: 1, borderColor: '#dbe6dc', borderRadius: 14, padding: 16},
  titleRow: {flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8},
  title: {fontSize: 19, fontWeight: '700', color: '#1b3325'},
  badge: {fontSize: 13, fontWeight: '700', color: '#225940', backgroundColor: '#e9f3ec',
    borderRadius: 8, overflow: 'hidden', paddingHorizontal: 9, paddingVertical: 4},
  description: {fontSize: 16, lineHeight: 24, color: '#405447', marginTop: 8},
  state: {fontSize: 14, color: '#5d7061', marginTop: 10},
  action: {minHeight: 50, backgroundColor: '#225940', borderRadius: 10, marginTop: 12,
    alignItems: 'center', justifyContent: 'center'},
  leaveAction: {backgroundColor: '#edf4ee', borderWidth: 1, borderColor: '#b8cdbd'},
  actionText: {fontSize: 16, fontWeight: '700', color: '#fff'},
  leaveText: {color: '#225940'},
  message: {fontSize: 16, lineHeight: 24, color: '#405447', marginTop: 14},
  error: {fontSize: 16, lineHeight: 24, color: '#a52626', marginTop: 14},
  retry: {minHeight: 50, backgroundColor: '#225940', borderRadius: 10, marginTop: 12,
    alignItems: 'center', justifyContent: 'center'},
  retryText: {fontSize: 16, fontWeight: '700', color: '#fff'},
});
