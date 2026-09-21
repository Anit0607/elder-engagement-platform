export type Language = 'en' | 'bn' | 'hi';

type Copy = {
  languageName: string; language: string; tagline: string; sectionLabel: string;
  home: string; circles: string; profile: string;
  homeTitle: string; homeIntro: string; homeCardTitle: string; homeCardBody: string;
  circlesTitle: string; circlesIntro: string; circlesCardTitle: string; circlesCardBody: string;
  profileTitle: string; profileIntro: string; profileCardTitle: string; profileCardBody: string;
  previewTitle: string; previewBody: string;
  signIn: string; signOut: string; signedIn: string; checkingAccount: string;
  accountUnavailable: string;
  confirmSignOut: string; cancel: string;
  yourName: string; age55: string; interests: string; interestsHint: string;
  state: string; city: string; notificationTimes: string; startTime: string; endTime: string;
  saveProfile: string; savingProfile: string; profileSaved: string; profileLoadFailed: string;
  profileSaveFailed: string; nameRequired: string; profileInvalid: string;
  profilePhoto: string; choosePhoto: string; uploadingPhoto: string;
  photoHelp: string; photoSaved: string; photoFailed: string;
  loadingProfile: string;
  yourDevices: string; thisDevice: string; anotherDevice: string; removeDevice: string;
  removeConfirm: string; deviceLoadFailed: string; noDevices: string;
  tryAgain: string;
  loadingCircles: string; circleLoadFailed: string; noCircles: string;
  suggested: string; joinedCircle: string; availableCircle: string; inactiveCircle: string;
  joinCircle: string; leaveCircle: string; leaveCircleConfirm: string;
  updatingCircle: string; circleLimit: string; circleChangeFailed: string;
};

// Provisional interface wording; client review is required before release.
export const copy: Record<Language, Copy> = {
  en: {
    languageName: 'English', language: 'Language', tagline: 'A place to stay connected',
    sectionLabel: 'Welcome', home: 'Home', circles: 'Circles', profile: 'Profile',
    homeTitle: 'Good to see you', homeIntro: 'Find familiar faces, shared interests and helpful updates in one place.',
    homeCardTitle: 'Your space', homeCardBody: 'Approved stories and events will appear here when they are available.',
    circlesTitle: 'Find your circle', circlesIntro: 'Explore groups built around the things you enjoy.',
    circlesCardTitle: 'Suggested circles', circlesCardBody: 'Your available groups will appear here after sign-in.',
    profileTitle: 'Your profile', profileIntro: 'Keep your details and preferences up to date.',
    profileCardTitle: 'Personal details', profileCardBody: 'Sign in to view and manage your profile.',
    previewTitle: 'Preview screen', previewBody: 'This screen is being connected to your secure account and live content.',
    signIn: 'Sign in with phone', signOut: 'Sign out', signedIn: 'You are signed in',
    checkingAccount: 'Checking your account…', accountUnavailable: 'Your account could not be checked. Try again when connected.',
    confirmSignOut: 'Sign out of Amiko on this phone?', cancel: 'Cancel',
    yourName: 'Your name', age55: 'Age group: 55+', interests: 'Your interests',
    interestsHint: 'Separate interests with commas', state: 'State', city: 'City',
    notificationTimes: 'Preferred notification times', startTime: 'From (24-hour time)', endTime: 'Until (24-hour time)',
    saveProfile: 'Save profile', savingProfile: 'Saving…', profileSaved: 'Profile saved',
    profileLoadFailed: 'Could not load your profile. Please try again when connected.',
    profileSaveFailed: 'Could not save your profile. Please try again.',
    nameRequired: 'Please enter your name (up to 120 characters).',
    profileInvalid: 'Please check your interests, location and notification times.',
    profilePhoto: 'Your profile photo', choosePhoto: 'Choose a profile photo', uploadingPhoto: 'Uploading photo…',
    photoHelp: 'JPEG, PNG or WebP; maximum 5 MB. You can leave the photo empty.',
    photoSaved: 'Photo saved', photoFailed: 'Photo could not be uploaded. Please try another image.',
    loadingProfile: 'Loading your profile…',
    yourDevices: 'Your signed-in devices', thisDevice: 'This phone', anotherDevice: 'Another device',
    removeDevice: 'Sign out device', removeConfirm: 'Sign out this device? It will need to sign in again.',
    deviceLoadFailed: 'Could not check devices. Please try again when connected.', noDevices: 'No devices found.',
    tryAgain: 'Try again',
    loadingCircles: 'Loading circles…', circleLoadFailed: 'Could not load circles. Please try again when connected.',
    noCircles: 'No circles are available yet.', suggested: 'Suggested', joinedCircle: 'You have joined',
    availableCircle: 'Available to join', inactiveCircle: 'Currently unavailable',
    joinCircle: 'Join circle', leaveCircle: 'Leave circle',
    leaveCircleConfirm: 'Leave this circle? You can join again while it remains available.',
    updatingCircle: 'Updating…', circleLimit: 'You have reached the circle limit. Leave a circle before joining another.',
    circleChangeFailed: 'Could not change your circle. Please try again.',
  },
  bn: {
    languageName: 'বাংলা', language: 'ভাষা', tagline: 'যোগাযোগে থাকার আপন জায়গা',
    sectionLabel: 'স্বাগতম', home: 'হোম', circles: 'দল', profile: 'প্রোফাইল',
    homeTitle: 'আপনাকে দেখে ভালো লাগছে', homeIntro: 'পরিচিত মানুষ, পছন্দের বিষয় এবং দরকারি খবর এক জায়গায় পান।',
    homeCardTitle: 'আপনার জায়গা', homeCardBody: 'অনুমোদিত গল্প ও অনুষ্ঠান পাওয়া গেলে এখানে দেখা যাবে।',
    circlesTitle: 'আপনার দল খুঁজুন', circlesIntro: 'আপনার পছন্দের বিষয় নিয়ে তৈরি দলগুলি দেখুন।',
    circlesCardTitle: 'প্রস্তাবিত দল', circlesCardBody: 'সাইন ইন করার পরে আপনার জন্য উপলব্ধ দলগুলি এখানে দেখা যাবে।',
    profileTitle: 'আপনার প্রোফাইল', profileIntro: 'নিজের তথ্য ও পছন্দ হালনাগাদ রাখুন।',
    profileCardTitle: 'ব্যক্তিগত তথ্য', profileCardBody: 'প্রোফাইল দেখতে ও বদলাতে সাইন ইন করুন।',
    previewTitle: 'নমুনা পর্দা', previewBody: 'এই পর্দা আপনার নিরাপদ অ্যাকাউন্ট ও লাইভ কনটেন্টের সঙ্গে যুক্ত করা হচ্ছে।',
    signIn: 'ফোন নম্বর দিয়ে সাইন ইন করুন', signOut: 'সাইন আউট', signedIn: 'আপনি সাইন ইন করেছেন',
    checkingAccount: 'আপনার অ্যাকাউন্ট দেখা হচ্ছে…', accountUnavailable: 'আপনার অ্যাকাউন্ট দেখা যায়নি। ইন্টারনেট যুক্ত করে আবার চেষ্টা করুন।',
    confirmSignOut: 'এই ফোনে Amiko থেকে সাইন আউট করবেন?', cancel: 'বাতিল',
    yourName: 'আপনার নাম', age55: 'বয়সের বিভাগ: ৫৫+', interests: 'আপনার আগ্রহ',
    interestsHint: 'কমা দিয়ে আলাদা করুন', state: 'রাজ্য', city: 'শহর',
    notificationTimes: 'বিজ্ঞপ্তি পাওয়ার পছন্দের সময়', startTime: 'শুরু (২৪ ঘণ্টার সময়)', endTime: 'শেষ (২৪ ঘণ্টার সময়)',
    saveProfile: 'প্রোফাইল সংরক্ষণ করুন', savingProfile: 'সংরক্ষণ হচ্ছে…', profileSaved: 'প্রোফাইল সংরক্ষিত হয়েছে',
    profileLoadFailed: 'প্রোফাইল খোলা যায়নি। ইন্টারনেট যুক্ত করে আবার চেষ্টা করুন।',
    profileSaveFailed: 'প্রোফাইল সংরক্ষণ করা যায়নি। আবার চেষ্টা করুন।',
    nameRequired: 'আপনার নাম লিখুন (সর্বোচ্চ ১২০ অক্ষর)।',
    profileInvalid: 'আগ্রহ, জায়গা ও বিজ্ঞপ্তির সময় পরীক্ষা করুন।',
    profilePhoto: 'আপনার প্রোফাইল ছবি', choosePhoto: 'প্রোফাইল ছবি বেছে নিন', uploadingPhoto: 'ছবি আপলোড হচ্ছে…',
    photoHelp: 'JPEG, PNG বা WebP; সর্বোচ্চ ৫ MB। ছবি না দিলেও চলবে।',
    photoSaved: 'ছবি সংরক্ষিত হয়েছে', photoFailed: 'ছবি আপলোড করা যায়নি। অন্য ছবি দিয়ে চেষ্টা করুন।',
    loadingProfile: 'প্রোফাইল খোলা হচ্ছে…',
    yourDevices: 'যেসব ডিভাইসে সাইন ইন আছে', thisDevice: 'এই ফোন', anotherDevice: 'অন্য ডিভাইস',
    removeDevice: 'ডিভাইস থেকে সাইন আউট', removeConfirm: 'এই ডিভাইস থেকে সাইন আউট করবেন? আবার সাইন ইন করতে হবে।',
    deviceLoadFailed: 'ডিভাইস দেখা যায়নি। ইন্টারনেট যুক্ত করে আবার চেষ্টা করুন।', noDevices: 'কোনো ডিভাইস পাওয়া যায়নি।',
    tryAgain: 'আবার চেষ্টা করুন',
    loadingCircles: 'দলগুলি খোলা হচ্ছে…', circleLoadFailed: 'দলগুলি খোলা যায়নি। ইন্টারনেট যুক্ত করে আবার চেষ্টা করুন।',
    noCircles: 'এখনও কোনো দল নেই।', suggested: 'প্রস্তাবিত', joinedCircle: 'আপনি এই দলে আছেন',
    availableCircle: 'যোগ দেওয়া যাবে', inactiveCircle: 'এখন উপলব্ধ নয়',
    joinCircle: 'দলে যোগ দিন', leaveCircle: 'দল ছাড়ুন',
    leaveCircleConfirm: 'এই দল ছাড়বেন? দলটি চালু থাকলে আবার যোগ দিতে পারবেন।',
    updatingCircle: 'হালনাগাদ হচ্ছে…', circleLimit: 'দলের সর্বোচ্চ সংখ্যায় পৌঁছেছেন। নতুন দলে যোগ দিতে আগে একটি দল ছাড়ুন।',
    circleChangeFailed: 'দলে পরিবর্তন করা যায়নি। আবার চেষ্টা করুন।',
  },
  hi: {
    languageName: 'हिन्दी', language: 'भाषा', tagline: 'जुड़े रहने की अपनी जगह',
    sectionLabel: 'स्वागत है', home: 'होम', circles: 'समूह', profile: 'प्रोफ़ाइल',
    homeTitle: 'आपसे मिलकर अच्छा लगा', homeIntro: 'परिचित लोगों, अपनी रुचियों और उपयोगी जानकारी से एक ही जगह जुड़ें।',
    homeCardTitle: 'आपकी जगह', homeCardBody: 'स्वीकृत कहानियाँ और कार्यक्रम उपलब्ध होने पर यहाँ दिखेंगे।',
    circlesTitle: 'अपना समूह खोजें', circlesIntro: 'अपनी रुचियों के अनुसार बने समूह देखें।',
    circlesCardTitle: 'सुझाए गए समूह', circlesCardBody: 'साइन इन करने के बाद उपलब्ध समूह यहाँ दिखेंगे।',
    profileTitle: 'आपकी प्रोफ़ाइल', profileIntro: 'अपनी जानकारी और पसंद को अपडेट रखें।',
    profileCardTitle: 'व्यक्तिगत जानकारी', profileCardBody: 'प्रोफ़ाइल देखने और बदलने के लिए साइन इन करें।',
    previewTitle: 'नमूना स्क्रीन', previewBody: 'इस स्क्रीन को आपके सुरक्षित खाते और लाइव सामग्री से जोड़ा जा रहा है।',
    signIn: 'फ़ोन नंबर से साइन इन करें', signOut: 'साइन आउट', signedIn: 'आप साइन इन हैं',
    checkingAccount: 'आपका खाता जाँचा जा रहा है…', accountUnavailable: 'आपका खाता जाँचा नहीं जा सका। इंटरनेट से जुड़कर फिर कोशिश करें।',
    confirmSignOut: 'इस फ़ोन पर Amiko से साइन आउट करें?', cancel: 'रद्द करें',
    yourName: 'आपका नाम', age55: 'आयु वर्ग: 55+', interests: 'आपकी रुचियाँ',
    interestsHint: 'रुचियों को अल्पविराम से अलग करें', state: 'राज्य', city: 'शहर',
    notificationTimes: 'सूचना पाने का पसंदीदा समय', startTime: 'शुरू (24 घंटे का समय)', endTime: 'अंत (24 घंटे का समय)',
    saveProfile: 'प्रोफ़ाइल सहेजें', savingProfile: 'सहेजा जा रहा है…', profileSaved: 'प्रोफ़ाइल सहेज दी गई',
    profileLoadFailed: 'प्रोफ़ाइल नहीं खुल सकी। इंटरनेट से जुड़कर फिर कोशिश करें।',
    profileSaveFailed: 'प्रोफ़ाइल सहेजी नहीं जा सकी। फिर कोशिश करें।',
    nameRequired: 'अपना नाम लिखें (अधिकतम 120 अक्षर)।',
    profileInvalid: 'रुचियाँ, स्थान और सूचना का समय जाँचें।',
    profilePhoto: 'आपकी प्रोफ़ाइल फ़ोटो', choosePhoto: 'प्रोफ़ाइल फ़ोटो चुनें', uploadingPhoto: 'फ़ोटो अपलोड हो रही है…',
    photoHelp: 'JPEG, PNG या WebP; अधिकतम 5 MB। फ़ोटो देना वैकल्पिक है।',
    photoSaved: 'फ़ोटो सहेज दी गई', photoFailed: 'फ़ोटो अपलोड नहीं हो सकी। दूसरी तस्वीर चुनें।',
    loadingProfile: 'प्रोफ़ाइल खोली जा रही है…',
    yourDevices: 'साइन इन किए गए उपकरण', thisDevice: 'यह फ़ोन', anotherDevice: 'दूसरा उपकरण',
    removeDevice: 'उपकरण से साइन आउट', removeConfirm: 'इस उपकरण से साइन आउट करें? फिर से साइन इन करना होगा।',
    deviceLoadFailed: 'उपकरण जाँचे नहीं जा सके। इंटरनेट से जुड़कर फिर कोशिश करें।', noDevices: 'कोई उपकरण नहीं मिला।',
    tryAgain: 'फिर कोशिश करें',
    loadingCircles: 'समूह खोले जा रहे हैं…', circleLoadFailed: 'समूह नहीं खुल सके। इंटरनेट से जुड़कर फिर कोशिश करें।',
    noCircles: 'अभी कोई समूह उपलब्ध नहीं है।', suggested: 'सुझाया गया', joinedCircle: 'आप इसमें शामिल हैं',
    availableCircle: 'शामिल हो सकते हैं', inactiveCircle: 'अभी उपलब्ध नहीं',
    joinCircle: 'समूह में शामिल हों', leaveCircle: 'समूह छोड़ें',
    leaveCircleConfirm: 'यह समूह छोड़ें? उपलब्ध रहने पर आप फिर शामिल हो सकते हैं।',
    updatingCircle: 'अपडेट हो रहा है…', circleLimit: 'आप समूहों की अधिकतम सीमा पर हैं। नया समूह चुनने से पहले एक समूह छोड़ें।',
    circleChangeFailed: 'समूह में बदलाव नहीं हो सका। फिर कोशिश करें।',
  },
};
