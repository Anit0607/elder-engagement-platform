export type Language = 'en' | 'bn' | 'hi';

type Copy = {
  languageName: string; language: string; tagline: string; sectionLabel: string;
  home: string; circles: string; profile: string;
  homeTitle: string; homeIntro: string; homeCardTitle: string; homeCardBody: string;
  circlesTitle: string; circlesIntro: string; circlesCardTitle: string; circlesCardBody: string;
  profileTitle: string; profileIntro: string; profileCardTitle: string; profileCardBody: string;
  previewTitle: string; previewBody: string;
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
  },
};
