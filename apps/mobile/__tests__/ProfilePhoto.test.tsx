import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import {ProfileEditor} from '../src/ProfileEditor';
import {getMemberProfile, uploadMemberPhoto} from '../src/memberSession';

jest.mock('../src/memberSession', () => ({
  getMemberProfile: jest.fn(), updateMemberProfile: jest.fn(), uploadMemberPhoto: jest.fn(),
}));

beforeEach(() => {
  jest.clearAllMocks();
  (getMemberProfile as jest.Mock).mockResolvedValue({
    displayName: 'Sample Member', preferredLanguage: 'en', ageGroup: null,
    interests: [], broadLocation: null, photoUrl: null,
    notificationWindow: {enabled: false, timeZone: 'Asia/Kolkata'},
  });
});

test('optional photo choice can be cancelled without changing the profile', async () => {
  (uploadMemberPhoto as jest.Mock).mockResolvedValue(null);
  let screen!: ReactTestRenderer.ReactTestRenderer;
  await ReactTestRenderer.act(async () => {
    screen = ReactTestRenderer.create(<ProfileEditor language="en" />);
  });
  const choose = screen.root.findAllByProps({accessibilityRole: 'button'})[0];
  await ReactTestRenderer.act(async () => choose.props.onPress());
  expect(uploadMemberPhoto).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(screen.toJSON())).not.toContain('Photo saved');
});

test('completed photo upload reports success', async () => {
  (uploadMemberPhoto as jest.Mock).mockResolvedValue({photoUrl: null});
  let screen!: ReactTestRenderer.ReactTestRenderer;
  await ReactTestRenderer.act(async () => {
    screen = ReactTestRenderer.create(<ProfileEditor language="en" />);
  });
  const choose = screen.root.findAllByProps({accessibilityRole: 'button'})[0];
  await ReactTestRenderer.act(async () => choose.props.onPress());
  expect(JSON.stringify(screen.toJSON())).toContain('Photo saved');
});

test('a new member saves the profile before adding a photo', async () => {
  (getMemberProfile as jest.Mock).mockResolvedValue(null);
  let screen!: ReactTestRenderer.ReactTestRenderer;
  await ReactTestRenderer.act(async () => {
    screen = ReactTestRenderer.create(<ProfileEditor language="en" />);
  });
  const choose = screen.root.findAllByProps({accessibilityRole: 'button'})[0];
  expect(choose.props.disabled).toBe(true);
  expect(JSON.stringify(screen.toJSON())).toContain('Save your profile first');
});

test('a temporary profile-loading problem can be retried', async () => {
  (getMemberProfile as jest.Mock).mockRejectedValueOnce(new Error('offline'));
  let screen!: ReactTestRenderer.ReactTestRenderer;
  await ReactTestRenderer.act(async () => {
    screen = ReactTestRenderer.create(<ProfileEditor language="en" />);
  });
  expect(JSON.stringify(screen.toJSON())).toContain('Could not load your profile');
  const retry = screen.root.findByProps({accessibilityRole: 'button'});
  await ReactTestRenderer.act(async () => retry.props.onPress());
  expect(JSON.stringify(screen.toJSON())).toContain('Sample Member');
});
