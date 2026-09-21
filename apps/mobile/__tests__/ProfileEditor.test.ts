import {makeProfileUpdate} from '../src/ProfileEditor';

const form = {
  name: '  Sample Member  ', age55: false, interests: 'music, music, gardening',
  state: 'West Bengal', city: 'Kolkata', notify: false, start: '', end: '',
};

test('profile can be saved without selecting 55+', () => {
  expect(makeProfileUpdate(form, 'bn')).toEqual({
    displayName: 'Sample Member', preferredLanguage: 'bn', ageGroup: null,
    interests: ['music', 'gardening'],
    broadLocation: {countryCode: 'IN', state: 'West Bengal', city: 'Kolkata'},
    notificationWindow: {enabled: false, timeZone: 'Asia/Kolkata', startLocalTime: null, endLocalTime: null},
  });
});

test('55+ is a profile choice, not a sign-up restriction', () => {
  expect(makeProfileUpdate({...form, age55: true}, 'en').ageGroup).toBe('55+');
  expect(makeProfileUpdate(form, 'en').ageGroup).toBeNull();
});

test('notification window requires two valid times', () => {
  expect(() => makeProfileUpdate({...form, notify: true, start: '25:00', end: '20:00'}, 'hi'))
    .toThrow('INVALID_TIME');
  expect(makeProfileUpdate({...form, notify: true, start: '09:00', end: '20:00'}, 'hi')
    .notificationWindow?.enabled).toBe(true);
});

test('profile rejects an empty name and oversized interests', () => {
  expect(() => makeProfileUpdate({...form, name: ' '}, 'en')).toThrow('INVALID_NAME');
  expect(() => makeProfileUpdate({...form, interests: 'x'.repeat(81)}, 'en')).toThrow('INVALID_INTERESTS');
});
